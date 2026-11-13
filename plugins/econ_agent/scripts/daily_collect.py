"""
每日采集入口（cron 调用）
采集热榜 + RSS + 导入今日日报 → 等待 agent 分析
用法:
  python3 daily_collect.py            # 全量：新闻 + 33只watchlist行情 + 关键词
  python3 daily_collect.py --lite     # 轻量：新闻 + 关键词，跳过行情同步（午盘/夜盘用）
  python3 daily_collect.py --no-prices  # 同上（别名）
"""
import sys
import time
import logging
sys.path.insert(0, "/root/.openclaw/workspace/econ_agent")
from core.db import get_conn, init_db
from core import collector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("daily_collect")

# 行情同步总预算（秒）——东财抽风时防止拖死整个 cron
PRICE_SYNC_BUDGET = 180


def main(skip_prices: bool = False):
    init_db()
    conn = get_conn()

    # ── 1. 采集热榜 + RSS ──
    t0 = time.time()
    stats = collector.collect_all(conn)
    total_new = sum(v["new"] for v in stats.values())
    for k, v in stats.items():
        if v["new"]:
            log.info("%s: +%d/%d", k, v["new"], v["total"])
    log.info("collected %d new items in %.0fs", total_new, time.time() - t0)

    # ── 2. 导入今日日报（若已生成）──
    today = __import__("datetime").date.today().strftime("%Y%m%d")
    patterns = [
        f"/root/.openclaw/workspace/daily_report/daily_report_{today}.md",
        f"/root/.openclaw/workspace/daily_report_{today}.md",
    ]
    for p in patterns:
        import os
        if os.path.exists(p):
            n = collector.import_daily_report(conn, p)
            log.info("daily report imported: +%d (%s)", n, p)
            break
    else:
        log.warning("today's daily report not found yet")

    # ── 3. 同步行情（带时间预算 + fallback）──
    if not skip_prices:
        from core import market
        syms = [r["symbol"] for r in conn.execute("SELECT symbol FROM asset_info WHERE watchlist=1")]
        ok = 0
        t0 = time.time()
        for s in syms:
            if time.time() - t0 > PRICE_SYNC_BUDGET:
                log.warning("price sync budget %ds exhausted, %d/%d done", PRICE_SYNC_BUDGET, ok, len(syms))
                break
            try:
                market.sync_with_fallback(conn, s)
                ok += 1
            except Exception as e:
                log.warning("price sync %s failed: %s", s, e)
        from scripts_helper import sync_gold_btc
        try:
            sync_gold_btc(conn)
        except Exception as e:
            log.warning("gold/btc sync: %s", e)
        conn.commit()
        log.info("prices synced: %d/%d in %.0fs", ok, len(syms), time.time() - t0)
    else:
        log.info("price sync skipped (--lite)")

    # ── 4. 关键词订阅匹配 ──
    try:
        from core.keywords import scan_unmatched
        n_kw = scan_unmatched(conn, hours=24)
        log.info("keyword matched: +%d hits", n_kw)
    except Exception as e:
        log.warning("keyword scan failed: %s", e)
    conn.close()


if __name__ == "__main__":
    skip = "--lite" in sys.argv or "--no-prices" in sys.argv
    main(skip_prices=skip)
