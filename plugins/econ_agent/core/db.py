"""
econ_agent 核心数据库层
SQLite，WAL 模式，支持并发读写
"""
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, date

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "econ_agent.db"

SCHEMA = """
-- ══════════════ 采集层：原始新闻 ══════════════
CREATE TABLE IF NOT EXISTS raw_news (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,             -- ISO datetime
    source      TEXT NOT NULL,              -- trendradar:wallstreetcn-hot / rss:cls / daily_report
    source_id   TEXT,                       -- 平台文章 id
    title       TEXT NOT NULL,
    url         TEXT,
    raw_json    TEXT,
    analyzed    INTEGER DEFAULT 0,
    analyzed_at TEXT,
    UNIQUE(source, title)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_unique ON raw_news(source, COALESCE(source_id,''), title);

-- ══════════════ 分析层：结构化事件 ══════════════
CREATE TABLE IF NOT EXISTS news_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date  TEXT NOT NULL,              -- YYYY-MM-DD
    title       TEXT NOT NULL,
    summary     TEXT,                       -- 事件摘要（2-3句）
    category    TEXT,                       -- macro/geopolitics/tech/energy/policy/company/market
    sentiment   INTEGER DEFAULT 0,          -- -100 ~ 100
    impact      INTEGER DEFAULT 1,          -- 1-5
    confidence  INTEGER DEFAULT 50,         -- 0-100
    keywords    TEXT,                       -- json array
    source_urls TEXT,
    created_at  TEXT NOT NULL,
    created_by  TEXT DEFAULT 'agent'        -- agent / import
);

-- 事件 × 资产 关联（一个事件可关联多个资产）
CREATE TABLE IF NOT EXISTS event_assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL REFERENCES news_events(id),
    symbol      TEXT NOT NULL,              -- 600519.SH / 0700.HK / NVDA.US / XAU / BTC
    name        TEXT,
    market      TEXT,                       -- CN/HK/US/COMMODITY/CRYPTO
    direction   INTEGER DEFAULT 0,          -- +1 利好 / -1 利空
    horizon     TEXT DEFAULT 'short',       -- short(1-5d)/mid(1-8w)/long(3m+)
    weight      REAL DEFAULT 1.0,           -- 关联强度 0-2
    created_at  TEXT NOT NULL
);

-- 事件 × 板块 关联
CREATE TABLE IF NOT EXISTS event_sectors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL REFERENCES news_events(id),
    sector      TEXT NOT NULL,              -- 半导体/白酒/黄金/银行/...
    direction   INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

-- ══════════════ 行情层 ══════════════
CREATE TABLE IF NOT EXISTS asset_info (
    symbol      TEXT PRIMARY KEY,
    name        TEXT,
    market      TEXT,                       -- CN/HK/US/COMMODITY/CRYPTO
    asset_type  TEXT,                       -- stock/index/etf/gold/btc
    sector      TEXT,                       -- 所属行业（个股）
    is_leader   INTEGER DEFAULT 0,          -- 是否板块龙头
    watchlist   INTEGER DEFAULT 1,          -- 是否在关注池
    added_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,              -- YYYY-MM-DD
    symbol      TEXT NOT NULL,
    open        REAL, high REAL, low REAL, close REAL,
    volume      REAL, amount REAL,
    source      TEXT DEFAULT 'eastmoney',
    UNIQUE(date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_prices_sym_date ON prices(symbol, date);

-- ══════════════ 信号层 ══════════════
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    name        TEXT,
    direction   TEXT NOT NULL,              -- BUY / SELL
    strength    INTEGER DEFAULT 3,          -- 1-5
    trigger_type TEXT DEFAULT 'mixed',      -- news / technical / mixed
    thesis      TEXT,                       -- 投资逻辑
    source_event_ids TEXT,                  -- json array of news_events.id
    status      TEXT DEFAULT 'open',        -- open / executed / cancelled / expired
    expires_at  TEXT,
    executed_at TEXT,
    exec_price  REAL,
    note        TEXT
);

-- ══════════════ 模拟交易层 ══════════════
CREATE TABLE IF NOT EXISTS portfolio (
    symbol      TEXT PRIMARY KEY,
    name        TEXT,
    shares      REAL NOT NULL DEFAULT 0,
    avg_cost    REAL NOT NULL DEFAULT 0,
    first_buy_at TEXT,
    last_updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    executed_at TEXT NOT NULL,
    settle_date TEXT,                       -- T+1 等
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,              -- BUY / SELL
    shares      REAL NOT NULL,
    price       REAL NOT NULL,
    amount      REAL NOT NULL,
    fee         REAL DEFAULT 0,
    signal_id   INTEGER,
    pnl_realized REAL,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS cash_balance (
    key TEXT PRIMARY KEY CHECK(key='cash'),
    amount REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_nav (
    date        TEXT PRIMARY KEY,
    nav         REAL NOT NULL,              -- 总净值
    cash        REAL NOT NULL,
    market_value REAL NOT NULL,
    total_pnl   REAL,                       -- 累计盈亏
    total_pnl_pct REAL,
    benchmark_nav REAL,                     -- 基准（沪深300）净值
    note        TEXT
);

-- ══════════════ 优化闭环：信号效果评估 ══════════════
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id   INTEGER NOT NULL,
    symbol      TEXT NOT NULL,
    direction   TEXT,
    created_at  TEXT,
    exec_date   TEXT,
    exec_price  REAL,
    eval_date   TEXT,                       -- 评估日
    ret_5d      REAL, ret_10d REAL, ret_20d REAL,
    max_fav     REAL,                       -- 期内最大有利变动%
    max_adv     REAL,                       -- 期内最大不利变动%
    closed_pnl  REAL,                       -- 平仓后实际盈亏%
    verdict     TEXT,                       -- win / loss / flat
    evaluated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outcomes_eval ON signal_outcomes(evaluated_at);

-- ══════════════ v2: 产业链传导图谱 ══════════════
CREATE TABLE IF NOT EXISTS chain_nodes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    chain   TEXT NOT NULL,
    node    TEXT NOT NULL,
    level   INTEGER NOT NULL,
    note    TEXT DEFAULT '',
    UNIQUE(chain, node)
);
CREATE TABLE IF NOT EXISTS chain_edges (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chain     TEXT NOT NULL,
    from_node TEXT NOT NULL,
    to_node   TEXT NOT NULL,
    lag_days  INTEGER DEFAULT 5,
    strength  REAL DEFAULT 0.5,
    note      TEXT DEFAULT '',
    evidence  TEXT DEFAULT '',
    UNIQUE(chain, from_node, to_node)
);
CREATE TABLE IF NOT EXISTS asset_factors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    mom_20_60     REAL,
    vol_factor    REAL,
    liq_factor    REAL,
    event_strength REAL,
    chain_heat    REAL,
    sector_rs     REAL,
    composite     REAL,
    UNIQUE(date, symbol)
);
CREATE TABLE IF NOT EXISTS chain_signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    chain       TEXT NOT NULL,
    from_node   TEXT NOT NULL,
    to_node     TEXT NOT NULL,
    from_ret_5d REAL,
    to_ret_5d   REAL,
    thesis      TEXT,
    status      TEXT DEFAULT 'open'
);

-- ══════════════ v2.5: 关键词订阅监控 ══════════════
CREATE TABLE IF NOT EXISTS keyword_hits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_news_id INTEGER NOT NULL,
    keyword     TEXT NOT NULL,
    priority    TEXT NOT NULL,            -- P0 即时 / P1 晨报汇总
    hit_at      TEXT NOT NULL,
    alerted     INTEGER DEFAULT 0,        -- 是否已推送钉钉
    alerted_at  TEXT,
    UNIQUE(raw_news_id, keyword)
);
CREATE INDEX IF NOT EXISTS idx_khits_alert ON keyword_hits(alerted, priority);
"""


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(db_path) if db_path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | str | None = None):
    conn = get_conn(db_path)
    conn.executescript(SCHEMA)
    # 初始资金 1,000,000 CNY
    conn.execute("INSERT OR IGNORE INTO cash_balance(key, amount) VALUES ('cash', 1000000)")
    conn.commit()
    conn.close()
    log.info("database initialized at %s", db_path or DB_PATH)


def upsert_price(conn, d: dict):
    conn.execute(
        """INSERT INTO prices(date, symbol, open, high, low, close, volume, amount, source)
           VALUES(:date,:symbol,:open,:high,:low,:close,:volume,:amount,:source)
           ON CONFLICT(date, symbol) DO UPDATE SET
             open=excluded.open, high=excluded.high, low=excluded.low,
             close=excluded.close, volume=excluded.volume, amount=excluded.amount""",
        d,
    )


def insert_raw_news(conn, items: list[dict]) -> int:
    """items: [{source, source_id, title, url, raw_json}] 去重插入，返回新增条数"""
    n = 0
    for it in items:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO raw_news(collected_at, source, source_id, title, url, raw_json)
                   VALUES(?,?,?,?,?,?)""",
                (it["collected_at"], it["source"], it.get("source_id"), it["title"],
                 it.get("url"), it.get("raw_json")),
            )
            n += conn.total_changes > 0
        except sqlite3.Error as e:
            log.warning("insert raw_news failed: %s", e)
    return n


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("✅ econ_agent.db initialized")
