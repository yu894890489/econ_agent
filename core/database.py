"""数据库管理"""

import aiosqlite
from typing import Any, Dict, List, Optional
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    """数据库管理器"""
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[aiosqlite.Connection] = None
    
    async def connect(self):
        """连接数据库"""
        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        logger.info(f"Connected to database: {self.db_path}")
    
    async def close(self):
        """关闭连接"""
        if self._conn:
            await self._conn.close()
            logger.info("Database connection closed")
    
    async def execute(self, sql: str, params: tuple = None):
        """执行 SQL"""
        if params:
            cursor = await self._conn.execute(sql, params)
        else:
            cursor = await self._conn.execute(sql)
        await self._conn.commit()
        return cursor
    
    async def fetch_one(self, sql: str, params: tuple = None) -> Optional[Dict]:
        """查询单条记录"""
        cursor = await self.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def fetch_all(self, sql: str, params: tuple = None) -> List[Dict]:
        """查询多条记录"""
        cursor = await self.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def init_schema(self):
        """初始化数据库表"""
        schema_statements = [
            """CREATE TABLE IF NOT EXISTS raw_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collected_at TEXT NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT,
                title TEXT NOT NULL,
                url TEXT,
                raw_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS news_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_date TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                category TEXT,
                impact TEXT,
                created_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                strength INTEGER,
                trigger_type TEXT,
                thesis TEXT,
                invalidation TEXT,
                status TEXT DEFAULT 'open',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                amount REAL NOT NULL,
                commission REAL DEFAULT 0,
                signal_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                quantity REAL NOT NULL,
                avg_cost REAL NOT NULL,
                current_price REAL,
                market_value REAL,
                pnl REAL,
                pnl_pct REAL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS daily_nav (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nav_date TEXT NOT NULL UNIQUE,
                nav REAL NOT NULL,
                cash REAL,
                market_value REAL,
                total_return_pct REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                priority TEXT DEFAULT 'P1',
                enabled INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS keyword_hits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hit_date TEXT NOT NULL,
                keyword TEXT NOT NULL,
                news_id INTEGER,
                title TEXT,
                alerted INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                outcome_date TEXT NOT NULL,
                return_pct REAL,
                holding_days INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS chain_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                chain TEXT NOT NULL,
                layer INTEGER,
                symbol TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS chain_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_node INTEGER NOT NULL,
                to_node INTEGER NOT NULL,
                lag_days INTEGER DEFAULT 0,
                strength REAL DEFAULT 1.0
            )""",
            """CREATE TABLE IF NOT EXISTS sector_strength (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sector TEXT NOT NULL,
                strength REAL,
                rs_rank REAL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_raw_news_source ON raw_news(source)",
            "CREATE INDEX IF NOT EXISTS idx_raw_news_collected ON raw_news(collected_at)",
            "CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)",
            "CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status)",
            "CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)",
            "CREATE INDEX IF NOT EXISTS idx_keyword_hits_keyword ON keyword_hits(keyword)",
        ]
        
        for sql in schema_statements:
            await self.execute(sql)
        
        logger.info("Database schema initialized")
    
    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Database not connected")
        return self._conn
