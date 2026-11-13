"""
关键词订阅监控（学 TrendRadar frequency_words 模式，结合投资场景改造）
- 加载 config/watch_keywords.json
- 对 raw_news 标题做 P0/P1 匹配 + 排除词过滤
- 命中写 keyword_hits（去重），供盘中即时推送 / 晨报汇总
"""
import json
import sqlite3
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "watch_keywords.json"


class KeywordMonitor:
    def __init__(self, config_path: Path | str = CONFIG):
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self.exclude = cfg.get("exclude", [])
        self.p0 = cfg.get("P0", {})
        self.p1 = cfg.get("P1", {})

    def match(self, title: str) -> list[tuple[str, str]]:
        """返回 [(keyword, priority), ...]；排除词命中返回空"""
        if any(w in title for w in self.exclude):
            return []
        hits = [(k, "P0") for k in self.p0 if k in title]
        hits += [(k, "P1") for k in self.p1 if k in title]
        return hits

    def note(self, keyword: str) -> str:
        return (self.p0.get(keyword) or self.p1.get(keyword) or {}).get("note", "")

    def sectors(self, keyword: str) -> list[str]:
        return (self.p0.get(keyword) or self.p1.get(keyword) or {}).get("sectors", [])


def scan_unmatched(conn: sqlite3.Connection, monitor: KeywordMonitor | None = None,
                   hours: int = 24) -> int:
    """扫描近期未匹配过关键词的 raw_news，命中写入 keyword_hits"""
    from core.db import now_iso
    mon = monitor or KeywordMonitor()
    rows = conn.execute("""SELECT id, title, collected_at FROM raw_news
                           WHERE collected_at >= datetime('now', ?)
                           AND id NOT IN (SELECT DISTINCT raw_news_id FROM keyword_hits)""",
                        (f"-{hours} hours",)).fetchall()
    now = now_iso()
    n = 0
    for r in rows:
        hits = mon.match(r["title"])
        for kw, pri in hits:
            try:
                conn.execute("INSERT OR IGNORE INTO keyword_hits(raw_news_id, keyword, priority, hit_at) VALUES(?,?,?,?)",
                             (r["id"], kw, pri, now))
                n += 1
            except sqlite3.Error:
                pass
    conn.commit()
    return n


def pending_alerts(conn: sqlite3.Connection, priority: str = "P0") -> list[dict]:
    """未推送的命中（按新闻聚合，附全部命中关键词）"""
    rows = conn.execute("""SELECT k.raw_news_id, k.keyword, k.priority, k.hit_at,
                           r.title, r.source, r.url
                           FROM keyword_hits k JOIN raw_news r ON k.raw_news_id=r.id
                           WHERE k.alerted=0 AND k.priority=?
                           ORDER BY k.hit_at DESC""", (priority,)).fetchall()
    agg: dict[int, dict] = {}
    for r in rows:
        d = agg.setdefault(r["raw_news_id"], {
            "raw_id": r["raw_news_id"], "title": r["title"], "source": r["source"],
            "url": r["url"], "hit_at": r["hit_at"], "keywords": [],
        })
        d["keywords"].append(r["keyword"])
    return list(agg.values())


def mark_alerted(conn: sqlite3.Connection, raw_ids: list[int]):
    from core.db import now_iso
    for rid in raw_ids:
        conn.execute("UPDATE keyword_hits SET alerted=1, alerted_at=? WHERE raw_news_id=?",
                     (now_iso(), rid))
    conn.commit()


def daily_digest(conn: sqlite3.Connection) -> dict:
    """晨报用：近24h全部命中按关键词聚合"""
    rows = conn.execute("""SELECT k.keyword, k.priority, r.title, r.source, k.hit_at
                           FROM keyword_hits k JOIN raw_news r ON k.raw_news_id=r.id
                           WHERE k.hit_at >= datetime('now', '-24 hours')
                           ORDER BY k.priority, k.keyword""").fetchall()
    digest: dict[str, list] = {}
    for r in rows:
        digest.setdefault(r["keyword"], []).append({"title": r["title"], "source": r["source"]})
    return digest
