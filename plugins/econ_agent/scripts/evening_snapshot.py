"""
收盘盯市（cron 调用，A股 15:00 后 / 美股收盘后）
净值快照 → 持仓盈亏 → 信号效果评估 → 钉钉持仓日报
用法: python3 evening_snapshot.py [--push]
"""
import sys
import json
import logging
sys.path.insert(0, "/root/.openclaw/workspace/econ_agent")
from core.db import get_conn
from core import portfolio, dingtalk
from scripts_helper import sync_gold_btc
from core import market

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("evening")


def evaluate_open_signals(conn):
    """评估已执行信号的后续表现（5/10/20日收益）→ signal_outcomes"""
    rows = conn.execute("""SELECT s.id, s.symbol, s.direction, s.created_at, s.exec_price, s.executed_at
                           FROM signals s WHERE s.status='executed'
                           AND s.id NOT IN (SELECT DISTINCT signal_id FROM signal_outcomes WHERE signal_id IS NOT NULL)
                           AND s.exec_price IS NOT NULL""").fetchall()
    n = 0
    for r in rows:
        px = conn.execute("""SELECT date, close FROM prices WHERE symbol=? AND date > ?
                             ORDER BY date ASC LIMIT 20""",
                          (r["symbol"], (r["executed_at"] or "")[:10])).fetchall()
        if len(px) < 5:
            continue
        closes = [p["close"] for p in px]
        base = r["exec_price"]
        if not base:
            continue
        dir_mul = 1 if r["direction"] == "BUY" else -1
        rets = [ (c / base - 1) * 100 * dir_mul for c in closes ]
        max_fav = max(rets)
        max_adv = min(rets)
        r5 = rets[4] if len(rets) > 4 else None
        r10 = rets[9] if len(rets) > 9 else None
        r20 = rets[19] if len(rets) > 19 else None
        verdict = "win" if (r5 or 0) > 1 else "loss" if (r5 or 0) < -1 else "flat"
        conn.execute("""INSERT INTO signal_outcomes(signal_id, symbol, direction, created_at, exec_date, exec_price,
                        eval_date, ret_5d, ret_10d, ret_20d, max_fav, max_adv, verdict, evaluated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
                     (r["id"], r["symbol"], r["direction"], r["created_at"],
                      (r["executed_at"] or "")[:10], base, px[0]["date"],
                      r5, r10, r20, max_fav, max_adv, verdict))
        n += 1
    conn.commit()
    return n


def main(push: bool = False):
    conn = get_conn()
    # 盯市核心：只同步持仓标的的价格（全池刷新交给晨报/夜盘，避免东财收盘后限流连坐超时）
    import time
    t0 = time.time()
    pos_syms = [r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM portfolio WHERE shares > 0").fetchall()]
    for s in pos_syms:
        if time.time() - t0 > 120:  # 同步总预算 120s
            log.warning("sync budget exhausted, using cached prices")
            break
        try:
            market.sync_with_fallback(conn, s)
        except Exception as e:
            log.warning("sync %s: %s (use cached)", s, e)
    try:
        sync_gold_btc(conn)
    except Exception as e:
        log.warning("sync gold/btc: %s", e)
    conn.commit()

    evaluated = evaluate_open_signals(conn)
    log.info("signal outcomes evaluated: %d", evaluated)

    n = portfolio.snapshot(conn)
    pos = portfolio.positions_report(conn)
    stats = portfolio.closed_trades_stats(conn, 30)
    conn.close()

    lines = [
        f"**净值** ¥{n['nav']:,.0f}（{n['pnl_pct']:+.2f}%）| 现金 ¥{n['cash']:,.0f} | 市值 ¥{n['market_value']:,.0f}",
    ]
    if pos:
        lines.append("\n**持仓**")
        for p in pos:
            emoji = "🟢" if p["pnl"] >= 0 else "🔴"
            lines.append(f"{emoji} {p['name']}({p['symbol']}) 成本{p['avg_cost']:.2f} 现价{p['price']:.2f} "
                         f"盈亏{p['pnl_pct']:+.1f}% 市值¥{p['market_value']:,.0f}")
    else:
        lines.append("持仓：空仓")
    if stats["trades"]:
        lines.append(f"\n**近30日已平仓** {stats['trades']}笔 | 胜率{stats['win_rate']:.0f}% | 盈亏¥{stats['pnl']:,.0f}")
    lines.append(f"信号评估更新：{evaluated}条")

    msg = "\n".join(lines)
    if push:
        r = dingtalk.send_markdown("持仓日报", msg)
        log.info("pushed: %s", r)
    return msg


if __name__ == "__main__":
    main(push="--push" in sys.argv)
