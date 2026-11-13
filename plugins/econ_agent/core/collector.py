"""
采集层：TrendRadar 多平台热榜 + RSS 财经源 + 每日日报
数据源：newsnow API（TrendRadar 同款）
"""
import re
import json
import time
import logging
import requests
import feedparser
from datetime import datetime
from .db import insert_raw_news, now_iso

log = logging.getLogger(__name__)

NEWSNOW_API = "https://newsnow.busiyi.world/api/s"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
}

# 重点财经/科技平台（对照 TrendRadar config.yaml 的平台 id）
FIN_SOURCES = [
    ("wallstreetcn-hot", "华尔街见闻"),
    ("cls-hot", "财联社"),
    ("toutiao", "今日头条"),
    ("baidu", "百度热搜"),
    ("36kr", "36氪"),
    ("ithome", "IT之家"),
    ("zhihu", "知乎"),
    ("weibo", "微博"),
]

# RSS 财经源（补充深度内容）
RSS_SOURCES = [
    ("rss:caixin", "https://www.caixin.com/feed/"),
    ("rss:wallstreetcn", "https://dedicated.wallstreetcn.com/rss.xml"),
    ("rss:cnstock", "http://news.cnstock.com/news/sns_rss/"),
]


def fetch_platform(source_id: str, retries: int = 3) -> list[dict]:
    """从 newsnow 抓取单个平台热榜"""
    for attempt in range(retries):
        try:
            r = requests.get(NEWSNOW_API, params={"id": source_id, "latest": True},
                             headers=HEADERS, timeout=20)
            data = r.json()
            if data.get("status") not in ("success", "cache"):
                raise ValueError(f"status={data.get('status')}")
            now = now_iso()
            items = []
            for it in data.get("items", []):
                items.append({
                    "collected_at": now,
                    "source": f"trendradar:{source_id}",
                    "source_id": str(it.get("id", "")),
                    "title": it.get("title", "").strip(),
                    "url": it.get("url", ""),
                    "raw_json": json.dumps(it, ensure_ascii=False),
                })
            return items
        except Exception as e:
            log.warning("fetch %s failed (attempt %d): %s", source_id, attempt + 1, e)
            time.sleep(3 * (attempt + 1))
    return []


def fetch_rss(source_id: str, url: str) -> list[dict]:
    """RSS 抓取（requests 带超时，避免 feedparser 裸连挂死）"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning("rss %s http %d", source_id, r.status_code)
            return []
        d = feedparser.parse(r.content)
        now = now_iso()
        items = []
        for e in d.entries[:30]:
            title = getattr(e, "title", "").strip()
            if not title:
                continue
            items.append({
                "collected_at": now,
                "source": source_id,
                "source_id": getattr(e, "id", getattr(e, "guid", "")),
                "title": title,
                "url": getattr(e, "link", ""),
                "raw_json": json.dumps({"summary": getattr(e, "summary", "")[:500]}, ensure_ascii=False),
            })
        return items
    except requests.RequestException as e:
        log.warning("rss %s network error: %s", source_id, e)
        return []
    except Exception as e:
        log.warning("rss %s parse error: %s", source_id, e)
        return []


def collect_all(conn, sources: list[str] | None = None) -> dict:
    """采集全部源，入库，返回统计"""
    stats = {}
    src_ids = sources or [s[0] for s in FIN_SOURCES]
    for sid in src_ids:
        items = fetch_platform(sid)
        if items:
            n = insert_raw_news(conn, items)
            stats[sid] = {"total": len(items), "new": n}
        else:
            stats[sid] = {"total": 0, "new": 0}
        time.sleep(1.2)  # 礼貌间隔
    for sid, name in RSS_SOURCES:
        items = fetch_rss(sid, name)
        if items:
            n = insert_raw_news(conn, items)
            stats[sid] = {"total": len(items), "new": n}
        time.sleep(0.8)
    conn.commit()
    return stats


def import_daily_report(conn, md_path: str) -> int:
    """把每日日报的关键段落作为事件源导入 raw_news（由 agent 分析时结构化）"""
    from pathlib import Path
    p = Path(md_path)
    if not p.exists():
        return 0
    text = p.read_text(encoding="utf-8")
    title_m = re.search(r"^#\s+(.+)$", text, re.M)
    title = title_m.group(1) if title_m else p.stem
    items = [{
        "collected_at": now_iso(),
        "source": "daily_report",
        "source_id": p.stem,
        "title": title,
        "url": "",
        "raw_json": json.dumps({"content": text}, ensure_ascii=False),
    }]
    n = insert_raw_news(conn, items)
    conn.commit()
    return n


if __name__ == "__main__":
    from .db import get_conn, init_db
    logging.basicConfig(level=logging.INFO)
    init_db()
    conn = get_conn()
    stats = collect_all(conn)
    for k, v in stats.items():
        print(f"{k}: {v['new']}/{v['total']} new")
    conn.close()
