"""
Keyword 插件 - 关键词订阅监控
从 econ_agent/core/keywords.py 提取，独立运行
"""
import sys
import asyncio
import logging
from pathlib import Path
from econ_harness.core.plugin import BasePlugin
from econ_harness.core.notify import notifier

# 复用 econ_agent 插件的 core 模块
ECON_AGENT_DIR = Path(__file__).parent.parent / "econ_agent"
sys.path.insert(0, str(ECON_AGENT_DIR))

logger = logging.getLogger(__name__)


class KeywordPlugin(BasePlugin):
    name = "keyword"
    version = "1.0.0"
    description = "关键词订阅、P0/P1 分级、命中推送"

    async def on_start(self):
        from core.db import init_db
        init_db()
        self.info("Keyword plugin started")

    async def on_stop(self):
        self.info("Keyword plugin stopped")

    async def on_task(self, task_name: str, **kwargs):
        tasks = {
            "scan": self.scan,
            "pending": self.pending,
            "push_p0": self.push_p0,
            "digest": self.digest,
            "add_keyword": self.add_keyword,
            "remove_keyword": self.remove_keyword,
            "list_keywords": self.list_keywords,
        }
        handler = tasks.get(task_name)
        if handler:
            return await handler(**kwargs)
        return None

    async def scan(self, hours: int = 24, **kwargs) -> dict:
        """扫描近 N 小时新闻，匹配关键词"""
        from core.db import get_conn
        from core.keywords import scan_unmatched

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            n = scan_unmatched(conn, hours=hours)
            conn.close()
            return n

        n = await loop.run_in_executor(None, _run)
        return {"status": "ok", "matched": n}

    async def pending(self, priority: str = "P0", **kwargs) -> dict:
        """查看待推送的命中"""
        from core.db import get_conn
        from core.keywords import pending_alerts

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            alerts = pending_alerts(conn, priority)
            conn.close()
            return alerts

        alerts = await loop.run_in_executor(None, _run)
        return {"status": "ok", "alerts": alerts}

    async def push_p0(self, **kwargs) -> dict:
        """推送 P0 命中到钉钉"""
        from core.db import get_conn
        from core.keywords import pending_alerts, mark_alerted, KeywordMonitor

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            alerts = pending_alerts(conn, "P0")
            if not alerts:
                conn.close()
                return {"pushed": 0, "message": "no pending P0 alerts"}

            mon = KeywordMonitor()

            # 按标题去重
            by_title = {}
            for a in alerts:
                t = a["title"]
                if t in by_title:
                    by_title[t]["keywords"] = list(
                        dict.fromkeys(by_title[t]["keywords"] + a["keywords"])
                    )
                else:
                    by_title[t] = a
            uniq = list(by_title.values())

            lines = []
            for a in uniq[:20]:
                kws = "/".join(a["keywords"])
                note = "；".join(
                    filter(None, [mon.note(k) for k in a["keywords"][:2]])
                )
                src = a["source"].replace("trendradar:", "").replace("rss:", "")
                lines.append(
                    f"- **[{kws}]** {a['title']}（{src}）"
                    f"{('—— ' + note) if note else ''}"
                )

            msg = "### 🔔 关键词监控 | 盘中快报\n\n" + "\n".join(lines) + \
                  "\n\n> 以上为关键词订阅命中的实时信号。"

            result = notifier.send_markdown(f"关键词监控 | {len(uniq)}条命中", msg)

            if result.get("ok"):
                mark_alerted(conn, [a["raw_id"] for a in alerts])

            conn.close()
            return {"pushed": len(uniq), "ok": result.get("ok", False)}

        return await loop.run_in_executor(None, _run)

    async def digest(self, **kwargs) -> dict:
        """生成 24h 关键词汇总文本"""
        from core.db import get_conn
        from core.keywords import daily_digest, KeywordMonitor

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            d = daily_digest(conn)
            mon = KeywordMonitor()
            conn.close()
            return d, mon

        d, mon = await loop.run_in_executor(None, _run)

        if not d:
            return {"status": "ok", "text": "（近24h无关键词命中）"}

        lines = ["### 📡 关键词监控 24h 汇总\n"]
        for kw, items in sorted(d.items()):
            lines.append(f"**{kw}**（{len(items)}条）")
            for it in items[:5]:
                src = it["source"].replace("trendradar:", "").replace("rss:", "")
                lines.append(f"  - {it['title']}（{src}）")
            if len(items) > 5:
                lines.append(f"  - …等{len(items)}条")
            lines.append("")

        return {"status": "ok", "text": "\n".join(lines), "keywords": list(d.keys())}

    async def add_keyword(self, keyword: str, priority: str = "P1", **kwargs) -> dict:
        """添加关键词"""
        # 写入配置文件
        config_path = ECON_AGENT_DIR / "config" / "watch_keywords.json"
        import json

        if config_path.exists():
            cfg = json.loads(config_path.read_text())
        else:
            cfg = {"P0": {}, "P1": {}, "exclude": []}

        if priority == "P0":
            cfg["P0"][keyword] = kwargs.get("note", "")
        else:
            cfg["P1"][keyword] = kwargs.get("note", "")

        config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        return {"status": "ok", "keyword": keyword, "priority": priority}

    async def remove_keyword(self, keyword: str, **kwargs) -> dict:
        """移除关键词"""
        config_path = ECON_AGENT_DIR / "config" / "watch_keywords.json"
        import json

        if not config_path.exists():
            return {"status": "error", "error": "config not found"}

        cfg = json.loads(config_path.read_text())
        removed = False
        for pri in ("P0", "P1"):
            if keyword in cfg.get(pri, {}):
                del cfg[pri][keyword]
                removed = True

        if removed:
            config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))

        return {"status": "ok", "removed": removed}

    async def list_keywords(self, **kwargs) -> dict:
        """列出所有关键词"""
        config_path = ECON_AGENT_DIR / "config" / "watch_keywords.json"
        import json

        if not config_path.exists():
            return {"status": "ok", "keywords": {"P0": [], "P1": []}}

        cfg = json.loads(config_path.read_text())
        return {
            "status": "ok",
            "keywords": {
                "P0": list(cfg.get("P0", {}).keys()),
                "P1": list(cfg.get("P1", {}).keys()),
                "exclude": cfg.get("exclude", []),
            },
        }
