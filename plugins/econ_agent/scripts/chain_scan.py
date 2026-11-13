"""
传导扫描器：检测产业链上"上游已动、下游未动"的滞后环节
逻辑：from_node 5日收益 > +3%（动量确认）且 to_node 5日收益 < +1.5%（未跟涨）
→ 依据边的 lag_days 与 strength 给出传导候选
"""
import sys
import argparse
import pandas as pd
sys.path.insert(0, "/root/.openclaw/workspace/econ_agent")
from core.db import get_conn, now_iso
from core.factors import NODE_PROXY, node_ret5, ret5


def scan(conn, up_thresh: float = 0.03, laggard_thresh: float = 0.015):
    edges = conn.execute("SELECT chain, from_node, to_node, lag_days, strength, note FROM chain_edges WHERE strength > 0").fetchall()
    rows = []
    for e in edges:
        fr, tr = node_ret5(conn, e["from_node"]), node_ret5(conn, e["to_node"])
        if fr is None or tr is None:
            continue
        fired = fr > up_thresh and tr < laggard_thresh
        if fr > up_thresh and tr < laggard_thresh:
            # 找下游节点未涨标的
            targets = NODE_PROXY.get(e["to_node"], [])
            tgt_info = []
            for s in targets:
                r5 = ret5(conn, s)
                if r5 is None:
                    continue
                pos = conn.execute("SELECT COUNT(*) c FROM prices WHERE symbol=?", (s,)).fetchone()["c"]
                tgt_info.append((s, round(r5 * 100, 2)))
            rows.append({
                "chain": e["chain"], "from_node": e["from_node"], "to_node": e["to_node"],
                "from_ret_5d": round(fr * 100, 2), "to_ret_5d": round(tr * 100, 2),
                "lag_days": e["lag_days"], "strength": e["strength"],
                "targets": tgt_info, "note": e["note"],
            })
    return pd.DataFrame(rows)


def macro_regime(conn) -> dict:
    """大行情快照：宏观状态 → 利多/利空产业链"""
    def r5(sym):
        v = ret5(conn, sym)
        return round(v * 100, 2) if v is not None else None
    gold, spx = r5("518880.SH"), r5("SPX.US")
    oil_proxy, btc = r5("600938.SH"), r5("BTC.USD")
    storage, semis = None, None
    rows = conn.execute("""SELECT sector, AVG(close) FROM (
        SELECT a.sector, p.symbol, p.close FROM prices p JOIN asset_info a ON p.symbol=a.symbol
        WHERE p.date=(SELECT MAX(date) FROM prices)) GROUP BY sector""").fetchall()
    sec_ret = {}
    for r in conn.execute("""SELECT a.sector,
        AVG(CASE WHEN p.date=(SELECT MAX(date) FROM prices p2 WHERE p2.symbol=p.symbol) THEN p.close END) /
        AVG(CASE WHEN p.date=(SELECT MAX(date) FROM prices p2 WHERE p2.symbol=p.symbol AND p2.date <= date((SELECT MAX(date) FROM prices p3 WHERE p3.symbol=p.symbol), '-6 day')) THEN p.close END) - 1 AS r5
        FROM prices p JOIN asset_info a ON p.symbol=a.symbol GROUP BY a.sector""").fetchall():
        if r["r5"] is not None:
            sec_ret[r["sector"]] = round(r["r5"] * 100, 2)
    return {"gold_5d": gold, "spx_5d": spx, "oil_proxy_5d": oil_proxy, "btc_5d": btc, "sector_5d": sec_ret}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--up", type=float, default=3.0, help="上游5日涨幅阈值%%")
    ap.add_argument("--lag", type=float, default=1.5, help="下游未涨阈值%%")
    ap.add_argument("--save", action="store_true", help="传导信号入库")
    args = ap.parse_args()

    conn = get_conn()
    pd.set_option("display.width", 200)
    df = scan(conn, args.up / 100, args.lag / 100)

    print(f"\n═══ 产业链传导扫描 {now_iso()[:10]}（上游>+{args.up}% 且 下游<+{args.lag}%）═══")
    if df.empty:
        print("（无传导信号：产业链同步或整体静止）")
    else:
        for _, r in df.iterrows():
            tgts = " ".join(f"{s}({v}%)" for s, v in r["targets"]) or "-"
            print(f"[{r['chain']}] {r['from_node']} {r['from_ret_5d']:+.1f}% → {r['to_node']} {r['to_ret_5d']:+.1f}%"
                  f" | 滞后{r['lag_days']}d 强度{r['strength']} | 候选: {tgts}")
            if args.save:
                conn.execute("""INSERT INTO chain_signals(created_at, chain, from_node, to_node,
                    from_ret_5d, to_ret_5d, thesis, status) VALUES(?,?,?,?,?,?,?,'open')""",
                    (now_iso(), r["chain"], r["from_node"], r["to_node"],
                     r["from_ret_5d"], r["to_ret_5d"], r["note"]))
        if args.save:
            conn.commit()
            print(f"\n{len(df)} 条传导信号已入库 chain_signals")

    print("\n── 大行情快照 ──")
    regime = macro_regime(conn)
    print(f"金5d {regime['gold_5d']}% | 标普5d {regime['spx_5d']}% | 油(海油代理)5d {regime['oil_proxy_5d']}% | BTC 5d {regime['btc_5d']}%")
    sec = sorted(regime["sector_5d"].items(), key=lambda x: -x[1])
    print("板块5日: " + " | ".join(f"{k} {v:+.1f}%" for k, v in sec))
    conn.close()


if __name__ == "__main__":
    main()
