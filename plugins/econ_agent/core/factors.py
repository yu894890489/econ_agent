"""
多因子引擎 v2（Barra 简化版）
因子：mom_20_60 | vol | liq | event_strength | chain_heat | sector_rs
流程：MAD 去极值 → z-score 标准化 → 加权合成 composite
权重初始等权，后续用 IC/IR 滚动修正
"""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/root/.openclaw/workspace/econ_agent")
from core.db import get_conn, today

# 因子权重（等权起步；信号积累后用 IC/IR 调）
W = {"mom_20_60": 0.20, "vol_factor": 0.15, "liq_factor": 0.10,
     "event_strength": 0.20, "chain_heat": 0.20, "sector_rs": 0.15}


def mad_winsorize(s: pd.Series, n: float = 3.0) -> pd.Series:
    med = s.median()
    mad = (s - med).abs().median()
    if mad == 0 or pd.isna(mad):
        return s
    hi, lo = med + n * 1.4826 * mad, med - n * 1.4826 * mad
    return s.clip(lo, hi)


def zscore(s: pd.Series) -> pd.Series:
    std = s.std()
    return (s - s.mean()) / std if std and not pd.isna(std) else s * 0


def load_close(conn, symbol) -> pd.DataFrame:
    rows = conn.execute("SELECT date, close, volume, amount FROM prices WHERE symbol=? ORDER BY date",
                        (symbol,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def calc_price_factors(df: pd.DataFrame) -> dict:
    """量价三因子：动量(20日为主60日辅助)、低波、流动性趋势"""
    if len(df) < 65:
        return {}
    c, amt = df["close"], df["amount"]
    ret = c.pct_change()
    mom20 = c.iloc[-1] / c.iloc[-21] - 1
    mom60 = c.iloc[-1] / c.iloc[-61] - 1
    mom_20_60 = 0.7 * mom20 + 0.3 * (mom60 / 3)  # 60日收益年化折算压低权重
    vol = ret.iloc[-20:].std() * (252 ** 0.5)
    vol_factor = -vol  # 低波正向（Barra/A股2026实证：低波稳定）
    liq = np.log(max(amt.iloc[-5:].mean(), 1)) - np.log(max(amt.iloc[-25:-5].mean(), 1))
    return {"mom_20_60": mom_20_60, "vol_factor": vol_factor, "liq_factor": liq}


def calc_event_strength(conn, symbol, lookback_days: int = 5) -> float:
    """近N日关联事件的 方向×impact×confidence 加权和（方向已对齐到该标的）"""
    rows = conn.execute("""SELECT ea.direction, ne.impact, ne.confidence, ne.sentiment, ne.event_date
                           FROM event_assets ea JOIN news_events ne ON ea.event_id=ne.id
                           WHERE ea.symbol=? AND ea.direction != 0
                           ORDER BY ne.event_date DESC LIMIT 30""", (symbol,)).fetchall()
    if not rows:
        return 0.0
    import datetime as dt
    cutoff = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    s = 0.0
    DIR_MAP = {"bullish": 1, "bearish": -1}
    IMPACT_MAP = {"low": 1.0, "medium": 3.0, "moderate": 3.0, "high": 5.0, "critical": 5.0}
    CONF_MAP = {"low": 40.0, "medium": 70.0, "high": 90.0}

    def _num(v, mp, default, scale_cap):
        if v is None or v == "":
            return default
        if isinstance(v, str) and v.strip().lower() in mp:
            return mp[v.strip().lower()]
        try:
            fv = float(v)
            if scale_cap == 100.0 and 0 < fv <= 1.0:
                fv *= 100.0  # 0.8 = 80% 风格
            return max(0.0, min(fv, scale_cap))
        except (TypeError, ValueError):
            return default

    for r in rows:
        if r["event_date"] < cutoff:
            break
        d = r["direction"]
        d = DIR_MAP.get(str(d).lower(), d) if isinstance(d, str) else d
        if not isinstance(d, (int, float)) or d == 0:
            continue
        imp = _num(r["impact"], IMPACT_MAP, 0.0, 5.0)
        conf = _num(r["confidence"], CONF_MAP, 50.0, 100.0)
        s += d * (imp / 5.0) * (conf / 100.0)
    return s


# 链上节点符号映射（节点→分析用代表标的；金价用518880代理XAU历史）
NODE_PROXY = {
    "云厂商capex": ["MSFT.US"], "GPU/ASIC": ["NVDA.US", "AMD.US", "688256.SH"],
    "晶圆代工": ["TSM.US", "688981.SH"], "HBM/存储": ["603986.SH"],
    "半导体设备": ["002371.SZ", "688012.SH"], "存储接口": ["688008.SH"],
    "AI服务器整机": ["601138.SH"], "PCB/高速板材": ["002463.SZ"],
    "光模块/光互联": ["300308.SZ"], "液冷/温控": ["002837.SZ"],
    "电源/电力设备": ["300274.SZ"], "铜/关键材料": ["601899.SH", "600362.SH"],
    "国际油价": ["600938.SH"],  # 无原油期货，用海油近似
    "油气开采": ["600938.SH", "601857.SH", "XOM.US"],
    "油运": ["600026.SH", "601872.SH"], "炼化": ["600028.SH"],
    "金价": ["518880.SH"], "黄金股": ["600547.SH", "600988.SH"],
    "创新药估值": ["600276.SH"],
}


def ret5(conn, symbol) -> float | None:
    df = load_close(conn, symbol)
    if len(df) < 6:
        return None
    return float(df["close"].iloc[-1] / df["close"].iloc[-6] - 1)


def node_ret5(conn, node) -> float | None:
    rets = [ret5(conn, s) for s in NODE_PROXY.get(node, [])]
    rets = [r for r in rets if r is not None]
    return float(np.mean(rets)) if rets else None


def calc_chain_heat(conn, symbol) -> float:
    """上游节点5日收益的 strength 加权和 → 该标的热度的传导项"""
    rows = conn.execute("""SELECT e.from_node, e.strength FROM chain_edges e
                           JOIN asset_info a ON 1=1
                           WHERE e.to_node = (SELECT sector FROM asset_info WHERE symbol=?)""",
                        (symbol,)).fetchall()
    if not rows:
        # 直接用标的所属节点：找包含该标的的节点
        node = None
        for n, syms in NODE_PROXY.items():
            if symbol in syms:
                node = n
                break
        if not node:
            return 0.0
        rows = conn.execute("SELECT from_node, strength FROM chain_edges WHERE to_node=?",
                            (node,)).fetchall()
    heat, wsum = 0.0, 0.0
    for r in rows:
        up = node_ret5(conn, r["from_node"])
        if up is None:
            continue
        heat += up * r["strength"]
        wsum += abs(r["strength"])
    return heat / wsum if wsum else 0.0


def calc_sector_rs(conn, symbol) -> float:
    row = conn.execute("SELECT sector FROM asset_info WHERE symbol=?", (symbol,)).fetchone()
    if not row or not row["sector"]:
        return 0.0
    peers = [r["symbol"] for r in conn.execute(
        "SELECT symbol FROM asset_info WHERE sector=? AND symbol!=? AND watchlist=1",
        (row["sector"], symbol)).fetchall()]
    mine = ret5(conn, symbol)
    if mine is None or not peers:
        return 0.0
    pr = [ret5(conn, s) for s in peers]
    pr = [x for x in pr if x is not None]
    return mine - float(np.mean(pr)) if pr else 0.0


def compute_all(conn, date_str: str | None = None) -> pd.DataFrame:
    date_str = date_str or today()
    symbols = [r["symbol"] for r in conn.execute(
        "SELECT symbol FROM asset_info WHERE watchlist=1").fetchall()]
    recs = []
    for sym in symbols:
        df = load_close(conn, sym)
        pf = calc_price_factors(df)
        if not pf:
            continue
        es = calc_event_strength(conn, sym)
        ch = calc_chain_heat(conn, sym)
        rs = calc_sector_rs(conn, sym)
        recs.append({"date": date_str, "symbol": sym,
                     "mom_20_60": pf["mom_20_60"], "vol_factor": pf["vol_factor"],
                     "liq_factor": pf["liq_factor"], "event_strength": es,
                     "chain_heat": ch, "sector_rs": rs})
    out = pd.DataFrame(recs)
    if out.empty:
        return out
    # MAD 去极值 + z-score
    for f in W:
        out[f] = zscore(mad_winsorize(out[f]))
    out["composite"] = sum(out[f] * w for f, w in W.items())
    out = out.sort_values("composite", ascending=False)
    # 入库
    for _, r in out.iterrows():
        conn.execute("""INSERT OR REPLACE INTO asset_factors
            (date, symbol, mom_20_60, vol_factor, liq_factor, event_strength, chain_heat, sector_rs, composite)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (r["date"], r["symbol"], r["mom_20_60"], r["vol_factor"], r["liq_factor"],
             r["event_strength"], r["chain_heat"], r["sector_rs"], r["composite"]))
    conn.commit()
    return out


if __name__ == "__main__":
    conn = get_conn()
    pd.set_option("display.width", 160)
    df = compute_all(conn)
    name_map = {r["symbol"]: r["name"] for r in conn.execute("SELECT symbol, name FROM asset_info").fetchall()}
    df["name"] = df["symbol"].map(name_map)
    cols = ["symbol", "name", "mom_20_60", "vol_factor", "event_strength", "chain_heat", "sector_rs", "composite"]
    print(f"\n═══ 多因子打分 {today()}（z-score，composite=加权和）═══")
    print(df[cols].round(2).to_string(index=False))
    conn.close()
