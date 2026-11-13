"""
模拟交易引擎
规则：
- 初始资金 1,000,000 CNY
- 按当日收盘价成交（A股 T+1 忽略，模拟盘以收盘价撮合）
- 单票仓位 ≤ 20% 净值；总仓位 ≤ 90%
- 费用：佣金万3（最低5元）+ 卖出印花税万5
- BTC/黄金以人民币计价并入净值（BTC 用 gold-api USD 价 × USDCNY 汇率）
"""
import json
import logging
from datetime import datetime, date
from .db import get_conn, upsert_price, now_iso
from . import market

log = logging.getLogger(__name__)

MAX_POSITION_PCT = 0.20      # 单票上限
MAX_TOTAL_PCT = 0.90         # 总仓位上限
MIN_CASH_PCT = 0.10          # 最低现金
COMMISSION = 0.0003          # 佣金万3
MIN_FEE = 5.0
STAMP_TAX = 0.0005           # 卖出印花税万5


def get_cash(conn) -> float:
    return conn.execute("SELECT amount FROM cash_balance WHERE key='cash'").fetchone()["amount"]


def get_price(conn, symbol: str, d: str | None = None) -> float | None:
    """取某日收盘价（默认最新），没有则从东财/远端同步一次"""
    d = d or db_today()
    row = conn.execute("SELECT close FROM prices WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
                       (symbol, d)).fetchone()
    if row and row["close"]:
        return row["close"]
    # 尝试同步
    try:
        if symbol == "BTC":
            px = market.fetch_btc()["cny"]
            return px
        n = market.sync_kline_to_db(conn, symbol, beg=(d[:4] + "0101"))
        conn.commit()
        row = conn.execute("SELECT close FROM prices WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
                           (symbol, d)).fetchone()
        return row["close"] if row else None
    except Exception as e:
        log.error("get_price %s failed: %s", symbol, e)
        return None


def db_today() -> str:
    return date.today().isoformat()


def nav(conn) -> dict:
    """当前净值"""
    cash = get_cash(conn)
    mv = 0.0
    for r in conn.execute("SELECT symbol, shares FROM portfolio WHERE shares > 0"):
        px = get_price(conn, r["symbol"]) or 0
        mv += r["shares"] * px
    total = cash + mv
    row = conn.execute("SELECT nav FROM daily_nav ORDER BY date DESC LIMIT 1").fetchone()
    base = row["nav"] if row else 1000000.0
    return {"nav": total, "cash": cash, "market_value": mv,
            "pnl": total - 1000000, "pnl_pct": (total / 1000000 - 1) * 100}


def execute_signal(conn, signal_id: int, exec_date: str | None = None, note: str = "") -> dict:
    """执行信号 → 成交记录 + 持仓更新"""
    sig = conn.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
    if not sig or sig["status"] != "open":
        return {"ok": False, "error": "signal not open"}
    sym = sig["symbol"]
    px = get_price(conn, sym, exec_date)
    if not px or px <= 0:
        return {"ok": False, "error": f"no price for {sym}"}
    d = exec_date or db_today()
    n = nav(conn)
    strength = sig["strength"] or 3

    if sig["direction"] == "BUY":
        # 仓位权重：strength 3→10%, 每±1增减3%，上限20%
        weight = min(0.10 + (strength - 3) * 0.03, MAX_POSITION_PCT)
        budget = min(n["nav"] * weight, n["cash"] * 0.98)
        # 总仓位约束
        max_invest = n["nav"] * MAX_TOTAL_PCT - n["market_value"]
        budget = min(budget, max(0, max_invest))
        if budget < 1000:
            return {"ok": False, "error": "insufficient budget/capacity"}
        fee = max(budget * COMMISSION, MIN_FEE)
        shares = budget / px
        cash_after = get_cash(conn) - budget - fee
        if cash_after < 0:
            return {"ok": False, "error": "cash short"}
        conn.execute("UPDATE cash_balance SET amount=? WHERE key='cash'", (cash_after,))
        cur = conn.execute("SELECT * FROM portfolio WHERE symbol=?", (sym,)).fetchone()
        if cur and cur["shares"] > 0:
            new_shares = cur["shares"] + shares
            new_cost = (cur["shares"] * cur["avg_cost"] + budget) / new_shares
            conn.execute("UPDATE portfolio SET shares=?, avg_cost=?, last_updated=? WHERE symbol=?",
                         (new_shares, new_cost, now_iso(), sym))
        else:
            conn.execute("""INSERT INTO portfolio(symbol, name, shares, avg_cost, first_buy_at, last_updated)
                            VALUES(?,?,?,?,?,?)
                            ON CONFLICT(symbol) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost,
                            name=excluded.name, first_buy_at=COALESCE(portfolio.first_buy_at, excluded.first_buy_at),
                            last_updated=excluded.last_updated""",
                         (sym, sig["name"], shares, px, d, now_iso()))
        conn.execute("""INSERT INTO trades(executed_at, symbol, side, shares, price, amount, fee, signal_id, note)
                        VALUES(?,?,?,?,?,?,?,?,?)""",
                     (now_iso(), sym, "BUY", shares, px, budget, fee, signal_id, note))
    else:  # SELL
        pos = conn.execute("SELECT * FROM portfolio WHERE symbol=?", (sym,)).fetchone()
        if not pos or pos["shares"] <= 0:
            return {"ok": False, "error": "no position"}
        shares = pos["shares"]
        amount = shares * px
        fee = max(amount * COMMISSION, MIN_FEE) + amount * STAMP_TAX
        pnl = (px - pos["avg_cost"]) * shares - fee
        conn.execute("UPDATE cash_balance SET amount=amount+?-? WHERE key='cash'", (amount, fee))
        conn.execute("UPDATE portfolio SET shares=0, last_updated=? WHERE symbol=?", (now_iso(), sym))
        conn.execute("""INSERT INTO trades(executed_at, symbol, side, shares, price, amount, fee, signal_id, pnl_realized, note)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (now_iso(), sym, "SELL", shares, px, amount, fee, signal_id, pnl, note))

    conn.execute("UPDATE signals SET status='executed', executed_at=?, exec_price=? WHERE id=?",
                 (now_iso(), px, signal_id))
    conn.commit()
    log.info("signal %d executed: %s %s @ %.2f", signal_id, sig["direction"], sym, px)
    return {"ok": True, "price": px, "date": d}


def close_position(conn, symbol: str, signal_id: int | None = None, note: str = "策略平仓") -> dict:
    pos = conn.execute("SELECT * FROM portfolio WHERE symbol=?", (symbol,)).fetchone()
    if not pos or pos["shares"] <= 0:
        return {"ok": False, "error": "no position"}
    # 建临时 SELL 信号
    conn.execute("""INSERT INTO signals(created_at, symbol, name, direction, strength, trigger_type, thesis, status)
                    VALUES(?,?,?,?,?,?,?,'open')""",
                 (now_iso(), symbol, pos["name"], "SELL", 3, "system", note))
    sid = conn.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    r = execute_signal(conn, sid)
    return r


def snapshot(conn, note: str = "") -> dict:
    """每日盯市快照"""
    n = nav(conn)
    pnl = n["nav"] - 1000000
    # 基准：沪深300
    bench = get_price(conn, "000300.SH")
    bench_nav = None
    if bench:
        row = conn.execute("SELECT date, benchmark_nav FROM daily_nav WHERE benchmark_nav IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
        first = conn.execute("SELECT close FROM prices WHERE symbol='000300.SH' ORDER BY date ASC LIMIT 1").fetchone()
        if first and first["close"]:
            bench_nav = 1000000 * bench / first["close"]
    d = db_today()
    conn.execute("""INSERT INTO daily_nav(date, nav, cash, market_value, total_pnl, total_pnl_pct, benchmark_nav, note)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(date) DO UPDATE SET nav=excluded.nav, cash=excluded.cash,
                    market_value=excluded.market_value, total_pnl=excluded.total_pnl,
                    total_pnl_pct=excluded.total_pnl_pct, benchmark_nav=excluded.benchmark_nav, note=excluded.note""",
                 (d, n["nav"], n["cash"], n["market_value"], pnl, n["pnl_pct"], bench_nav, note))
    conn.commit()
    return n


def positions_report(conn) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM portfolio WHERE shares > 0"):
        px = get_price(conn, r["symbol"]) or r["avg_cost"]
        mv = r["shares"] * px
        pnl = (px - r["avg_cost"]) * r["shares"]
        out.append({**dict(r), "price": px, "market_value": mv,
                    "pnl": pnl, "pnl_pct": (px / r["avg_cost"] - 1) * 100 if r["avg_cost"] else 0})
    return out


def closed_trades_stats(conn, days: int = 30) -> dict:
    row = conn.execute("""SELECT COUNT(*) n, SUM(pnl_realized) pnl,
                          SUM(CASE WHEN pnl_realized>0 THEN 1 ELSE 0 END) wins
                          FROM trades WHERE side='SELL' AND pnl_realized IS NOT NULL
                          AND executed_at >= datetime('now', ?)""", (f"-{days} days",)).fetchone()
    n, pnl, wins = row["n"] or 0, row["pnl"] or 0, row["wins"] or 0
    return {"trades": n, "pnl": pnl, "win_rate": wins / n * 100 if n else 0}


if __name__ == "__main__":
    from .db import init_db
    logging.basicConfig(level=logging.INFO)
    init_db()
    conn = get_conn()
    print(json.dumps(nav(conn), indent=1))
    print(json.dumps(positions_report(conn), indent=1))
    conn.close()
