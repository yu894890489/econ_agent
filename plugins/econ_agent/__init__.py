"""
Econ Agent 插件 - 经济分析智能体
整合原 /workspace/econ_agent 全部功能
"""
import sys
import asyncio
import logging
from pathlib import Path
from econ_harness.core.plugin import BasePlugin
from econ_harness.core.notify import notifier

# 将插件目录加入 path，使 core/scripts 可导入
PLUGIN_DIR = Path(__file__).parent
sys.path.insert(0, str(PLUGIN_DIR))

logger = logging.getLogger(__name__)


class EconAgentPlugin(BasePlugin):
    name = "econ_agent"
    version = "1.0.0"
    description = "新闻分析、信号生成、产业链扫描、模拟交易"

    async def on_start(self):
        """初始化数据库"""
        from core.db import init_db, get_conn
        init_db()
        self.info("Econ Agent plugin started, database initialized")

    async def on_stop(self):
        self.info("Econ Agent plugin stopped")

    async def on_task(self, task_name: str, **kwargs):
        """处理任务"""
        tasks = {
            "daily_collect": self.daily_collect,
            "morning_report": self.morning_report,
            "evening_snapshot": self.evening_snapshot,
            "keyword_scan": self.keyword_scan,
            "chain_scan": self.chain_scan,
            "factor_compute": self.factor_compute,
            "get_nav": self.get_nav,
            "get_positions": self.get_positions,
        }
        handler = tasks.get(task_name)
        if handler:
            return await handler(**kwargs)
        return None

    async def daily_collect(self, **kwargs) -> dict:
        """每日采集：热榜 + RSS + 关键词匹配"""
        from core.db import get_conn
        from core import collector
        from core.keywords import scan_unmatched

        loop = asyncio.get_event_loop()
        
        def _run():
            conn = get_conn()
            stats = collector.collect_all(conn)
            n_kw = scan_unmatched(conn, hours=24)
            conn.close()
            return stats, n_kw

        stats, n_kw = await loop.run_in_executor(None, _run)
        total_new = sum(v["new"] for v in stats.values())
        return {
            "status": "ok",
            "news_collected": total_new,
            "keyword_matched": n_kw,
            "sources": stats,
        }

    async def morning_report(self, **kwargs) -> dict:
        """晨报分析（简化版，完整版由 cron agentTurn 执行）"""
        from core.db import get_conn
        from core import portfolio
        from core.keywords import daily_digest

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            nav_data = portfolio.nav(conn)
            pos = portfolio.positions_report(conn)
            digest = daily_digest(conn)
            conn.close()
            return nav_data, pos, digest

        nav_data, pos, digest = await loop.run_in_executor(None, _run)

        # 构建晨报文本
        lines = ["## 🌅 经济分析师晨报\n"]
        lines.append(f"### 净值\n- NAV: ¥{nav_data['nav']:,.0f}（{nav_data['pnl_pct']:+.2f}%）")
        lines.append(f"- 现金: ¥{nav_data['cash']:,.0f}")
        lines.append(f"- 市值: ¥{nav_data['market_value']:,.0f}\n")

        if pos:
            lines.append("### 持仓")
            for p in pos:
                emoji = "🟢" if p["pnl"] >= 0 else "🔴"
                lines.append(f"- {emoji} {p['name']}({p['symbol']}) 盈亏{p['pnl_pct']:+.1f}%")
        else:
            lines.append("### 持仓\n- 空仓")

        if digest:
            lines.append("\n### 关键词监控 24h")
            for kw, items in list(digest.items())[:10]:
                lines.append(f"- **{kw}**: {len(items)}条")

        text = "\n".join(lines)
        result = notifier.send_markdown("经济分析师晨报", text)
        return {"status": "ok", "pushed": result.get("ok", False)}

    async def evening_snapshot(self, push: bool = False, **kwargs) -> dict:
        """收盘盯市"""
        loop = asyncio.get_event_loop()

        def _run():
            # 调用原脚本逻辑
            sys.path.insert(0, str(PLUGIN_DIR / "scripts"))
            from scripts.evening_snapshot import main
            msg = main(push=push)
            return msg

        msg = await loop.run_in_executor(None, _run)
        return {"status": "ok", "report": msg}

    async def keyword_scan(self, **kwargs) -> dict:
        """关键词扫描"""
        from core.db import get_conn
        from core.keywords import scan_unmatched, pending_alerts

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            n = scan_unmatched(conn, hours=24)
            p0 = pending_alerts(conn, "P0")
            p1 = pending_alerts(conn, "P1")
            conn.close()
            return n, p0, p1

        n, p0, p1 = await loop.run_in_executor(None, _run)
        return {
            "status": "ok",
            "matched": n,
            "pending_p0": len(p0),
            "pending_p1": len(p1),
        }

    async def chain_scan(self, **kwargs) -> dict:
        """产业链传导扫描"""
        loop = asyncio.get_event_loop()

        def _run():
            sys.path.insert(0, str(PLUGIN_DIR / "scripts"))
            from scripts.chain_scan import main
            # chain_scan 需要 --save 参数
            import subprocess
            result = subprocess.run(
                [sys.executable, str(PLUGIN_DIR / "scripts" / "chain_scan.py"), "--save"],
                capture_output=True, text=True, cwd=str(PLUGIN_DIR)
            )
            return result.stdout

        output = await loop.run_in_executor(None, _run)
        return {"status": "ok", "output": output}

    async def factor_compute(self, **kwargs) -> dict:
        """多因子打分"""
        from core.db import get_conn
        from core import factors

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            df = factors.compute_all(conn)
            conn.close()
            return df

        df = await loop.run_in_executor(None, _run)
        if df.empty:
            return {"status": "ok", "factors": []}

        top = df.head(10).to_dict("records")
        return {"status": "ok", "factors": top}

    async def get_nav(self, **kwargs) -> dict:
        """获取当前净值"""
        from core.db import get_conn
        from core import portfolio

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            n = portfolio.nav(conn)
            conn.close()
            return n

        nav_data = await loop.run_in_executor(None, _run)
        return {"status": "ok", **nav_data}

    async def get_positions(self, **kwargs) -> dict:
        """获取当前持仓"""
        from core.db import get_conn
        from core import portfolio

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            pos = portfolio.positions_report(conn)
            conn.close()
            return pos

        pos = await loop.run_in_executor(None, _run)
        return {"status": "ok", "positions": pos}
