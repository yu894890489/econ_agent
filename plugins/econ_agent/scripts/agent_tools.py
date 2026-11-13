"""
分析支撑工具：技术指标 + 板块强度 + 信号表现
供 agent 在分析新闻、生成信号时调用（量化辅助层）
"""
import sys
import json
import logging
import pandas as pd
import numpy as np
sys.path.insert(0, "/root/.openclaw/workspace/econ_agent")
from core.db import get_conn

log = logging.getLogger(__name__)


def load_ohlc(conn, symbol: str, days: int = 120) -> pd.DataFrame:
    rows = conn.execute("""SELECT date, open, high, low, close, volume FROM prices
                           WHERE symbol=? ORDER BY date DESC LIMIT ?""", (symbol, days)).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows]).iloc[::-1].reset_index(drop=True)
    return df


def tech_summary(symbol: str) -> dict:
    """单标的：趋势/动量/超买超卖/位置"""
    conn = get_conn()
    df = load_ohlc(conn, symbol)
    if df.empty or len(df) < 30:
        conn.close()
        return {"error": "insufficient data"}
    c = df["close"]
    out = {"symbol": symbol, "last": round(float(c.iloc[-1]), 3), "date": str(df["date"].iloc[-1])}
    for n in (5, 10, 20, 60):
        out[f"ma{n}"] = round(float(c.rolling(n).mean().iloc[-1]), 3)
    out["trend"] = "up" if out["last"] > out["ma20"] > out.get("ma60", out["ma20"]) else \
                   "down" if out["last"] < out["ma20"] < out.get("ma60", out["ma20"]) else "mixed"
    # MACD
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    out["macd_dif"] = round(float(dif.iloc[-1]), 4)
    out["macd_dea"] = round(float(dea.iloc[-1]), 4)
    out["macd_hist"] = round(float((dif - dea).iloc[-1]), 4)
    out["macd_cross"] = "golden" if dif.iloc[-2] <= dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1] else \
                        "dead" if dif.iloc[-2] >= dea.iloc[-2] and dif.iloc[-1] < dea.iloc[-1] else "none"
    # RSI14
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_val = 100 - 100 / (1 + rs.iloc[-1])
    out["rsi14"] = round(float(rsi_val), 1) if not np.isnan(rsi_val) else 50.0
    # 动量 & 位置
    out["ret_5d"] = round(float(c.iloc[-1] / c.iloc[-6] - 1) * 100, 2) if len(c) > 5 else 0
    out["ret_20d"] = round(float(c.iloc[-1] / c.iloc[-21] - 1) * 100, 2) if len(c) > 20 else 0
    out["ret_60d"] = round(float(c.iloc[-1] / c.iloc[-61] - 1) * 100, 2) if len(c) > 60 else 0
    hi, lo = float(c.max()), float(c.min())
    out["pct_of_range"] = round((out["last"] - lo) / (hi - lo) * 100, 1) if hi > lo else 50
    out["vol_20d"] = round(float(c.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252) * 100), 1)
    out["avg_amt_20d"] = round(float((df["close"] * df["volume"]).rolling(20).mean().iloc[-1] / 1e8), 2)
    conn.close()
    return out


def sector_strength() -> list[dict]:
    """关注池板块强度榜：近5日/20日板块平均收益"""
    conn = get_conn()
    rows = conn.execute("""SELECT DISTINCT sector FROM asset_info
                           WHERE sector NOT LIKE '%基准%' AND watchlist=1""").fetchall()
    out = []
    for r in rows:
        sector = r["sector"]
        syms = conn.execute("""SELECT symbol FROM asset_info WHERE sector=? AND watchlist=1""",
                            (sector,)).fetchall()
        rets5, rets20 = [], []
        for s in syms:
            t = tech_summary(s["symbol"])
            if "ret_5d" in t:
                rets5.append(t["ret_5d"])
                rets20.append(t.get("ret_20d", 0))
        if rets5:
            out.append({"sector": sector, "n": len(rets5),
                        "ret_5d": round(sum(rets5) / len(rets5), 2),
                        "ret_20d": round(sum(rets20) / len(rets20), 2)})
    out.sort(key=lambda x: x["ret_5d"] * 0.6 + x["ret_20d"] * 0.4, reverse=True)
    conn.close()
    return out


def watchlist_pulse() -> list[dict]:
    """全关注池技术面速览"""
    conn = get_conn()
    syms = [r["symbol"] for r in conn.execute("SELECT symbol FROM asset_info WHERE watchlist=1")]
    conn.close()
    return [tech_summary(s) for s in syms]


def signal_performance(days: int = 30) -> dict:
    """已平仓信号表现（优化闭环的核心反馈）"""
    conn = get_conn()
    row = conn.execute("""SELECT COUNT(*) n, SUM(CASE WHEN pnl_realized>0 THEN 1 ELSE 0 END) wins,
                          SUM(pnl_realized) pnl, AVG(pnl_realized) avg_pnl,
                          AVG(CASE WHEN pnl_realized>0 THEN pnl_realized END) avg_win,
                          AVG(CASE WHEN pnl_realized<0 THEN pnl_realized END) avg_loss
                          FROM trades WHERE side='SELL' AND pnl_realized IS NOT NULL
                          AND executed_at >= datetime('now', ?)""", (f"-{days} days",)).fetchone()
    d = dict(row) if row else {}
    d["win_rate"] = round(d["wins"] / d["n"] * 100, 1) if d.get("n") else 0
    d.pop("wins", None)
    # 按触发类型拆分
    by_type = {}
    for r in conn.execute("""SELECT s.trigger_type t, COUNT(*) n,
                             SUM(CASE WHEN tr.pnl_realized>0 THEN 1 ELSE 0 END) w, SUM(tr.pnl_realized) pnl
                             FROM trades tr JOIN signals s ON tr.signal_id=s.id
                             WHERE tr.side='SELL' AND tr.pnl_realized IS NOT NULL
                             AND tr.executed_at >= datetime('now', ?) GROUP BY s.trigger_type""",
                          (f"-{days} days",)):
        by_type[r["t"]] = {"n": r["n"], "win_rate": round(r["w"] / r["n"] * 100, 1) if r["n"] else 0,
                           "pnl": round(r["pnl"] or 0, 0)}
    d["by_trigger"] = by_type
    conn.close()
    return d


def open_signals(conn=None) -> list[dict]:
    own = conn is None
    if own:
        conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM signals WHERE status='open' ORDER BY created_at DESC")]
    if own:
        conn.close()
    return rows


def pending_news(limit: int = 50) -> list[dict]:
    """待分析新闻（含日报）"""
    conn = get_conn()
    rows = [dict(r) for r in conn.execute(
        """SELECT * FROM raw_news WHERE analyzed=0 ORDER BY collected_at DESC LIMIT ?""", (limit,))]
    conn.close()
    return rows


def fmt_pct(x):
    return f"{x:+.2f}%"


if __name__ == "__main__":
    print(json.dumps(tech_summary("518880.SH"), ensure_ascii=False, indent=1))
    print(json.dumps(sector_strength(), ensure_ascii=False, indent=1))
