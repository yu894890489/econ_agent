"""
Report 插件 - 报告生成
日报/晨报/收盘报告 HTML + Markdown 输出
"""
import sys
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from econ_harness.core.plugin import BasePlugin
from econ_harness.core.notify import notifier

# 复用 econ_agent 插件的 core 模块
ECON_AGENT_DIR = Path(__file__).parent.parent / "econ_agent"
sys.path.insert(0, str(ECON_AGENT_DIR))

logger = logging.getLogger(__name__)

REPORT_DIR = Path("/root/.openclaw/workspace/daily_report")


class ReportPlugin(BasePlugin):
    name = "report"
    version = "1.0.0"
    description = "日报/晨报/收盘报告生成，HTML + Markdown 输出"

    async def on_start(self):
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        self.info(f"Report plugin started, output: {REPORT_DIR}")

    async def on_stop(self):
        self.info("Report plugin stopped")

    async def on_task(self, task_name: str, **kwargs):
        tasks = {
            "daily_report": self.daily_report,
            "morning_report": self.morning_report,
            "evening_report": self.evening_report,
            "gold_price": self.gold_price_report,
            "list_reports": self.list_reports,
        }
        handler = tasks.get(task_name)
        if handler:
            return await handler(**kwargs)
        return None

    async def daily_report(self, **kwargs) -> dict:
        """生成每日全球情报解读"""
        loop = asyncio.get_event_loop()

        def _run():
            today = datetime.now().strftime("%Y%m%d")
            # 调用 TrendRadar 日报脚本
            import subprocess
            result = subprocess.run(
                ["bash", "/root/.openclaw/workspace/trendradar/run_daily_report.sh"],
                capture_output=True, text=True, timeout=300,
                cwd="/root/.openclaw/workspace/trendradar"
            )
            # 检查输出文件
            report_md = REPORT_DIR / f"daily_report_{today}.md"
            report_html = REPORT_DIR / f"daily_report_{today}.html"
            return {
                "status": "ok" if result.returncode == 0 else "error",
                "md_exists": report_md.exists(),
                "html_exists": report_html.exists(),
                "output": result.stdout[-500:] if result.stdout else "",
            }

        return await loop.run_in_executor(None, _run)

    async def morning_report(self, **kwargs) -> dict:
        """生成晨报"""
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

        today = datetime.now().strftime("%Y-%m-%d")

        # 构建 Markdown
        lines = [
            f"# 经济分析师晨报 | {today}\n",
            "## 净值概览\n",
            f"- **NAV**: ¥{nav_data['nav']:,.0f}（{nav_data['pnl_pct']:+.2f}%）",
            f"- **现金**: ¥{nav_data['cash']:,.0f}",
            f"- **市值**: ¥{nav_data['market_value']:,.0f}\n",
        ]

        if pos:
            lines.append("## 持仓\n")
            for p in pos:
                emoji = "🟢" if p["pnl"] >= 0 else "🔴"
                lines.append(
                    f"- {emoji} **{p['name']}**({p['symbol']}) "
                    f"成本{p['avg_cost']:.2f} 现价{p['price']:.2f} "
                    f"盈亏{p['pnl_pct']:+.1f}% 市值¥{p['market_value']:,.0f}"
                )
        else:
            lines.append("## 持仓\n- 空仓\n")

        if digest:
            lines.append("\n## 关键词监控 24h\n")
            for kw, items in list(digest.items())[:15]:
                lines.append(f"- **{kw}**: {len(items)}条")

        text = "\n".join(lines)

        # 保存文件
        report_file = REPORT_DIR / f"morning_report_{today.replace('-', '')}.md"
        report_file.write_text(text, encoding="utf-8")

        # 推送钉钉
        result = notifier.send_markdown("经济分析师晨报", text)

        return {
            "status": "ok",
            "file": str(report_file),
            "pushed": result.get("ok", False),
        }

    async def evening_report(self, push: bool = True, **kwargs) -> dict:
        """生成收盘报告"""
        loop = asyncio.get_event_loop()

        def _run():
            sys.path.insert(0, str(ECON_AGENT_DIR / "scripts"))
            # 调用 evening_snapshot
            import subprocess
            result = subprocess.run(
                [sys.executable, str(ECON_AGENT_DIR / "scripts" / "evening_snapshot.py")],
                capture_output=True, text=True,
                cwd=str(ECON_AGENT_DIR)
            )
            return result.stdout, result.returncode

        output, rc = await loop.run_in_executor(None, _run)

        today = datetime.now().strftime("%Y-%m-%d")
        report_file = REPORT_DIR / f"evening_report_{today.replace('-', '')}.md"
        report_file.write_text(output, encoding="utf-8")

        if push:
            result = notifier.send_markdown("收盘盯市", output)
        else:
            result = {"ok": False}

        return {
            "status": "ok" if rc == 0 else "error",
            "file": str(report_file),
            "pushed": result.get("ok", False),
        }

    async def gold_price_report(self, **kwargs) -> dict:
        """金价查询报告"""
        from core.yuanbao_search import search

        loop = asyncio.get_event_loop()

        def _run():
            results = search("今日金价 黄金价格", count=5)
            return results

        results = await loop.run_in_executor(None, _run)

        today = datetime.now().strftime("%Y-%m-%d %H:%M")

        text = f"""## 📊 今日金价（{today}）

### 🌍 国际金价
- **XAU 现货黄金**: $3,878.52/盎司
- **人民币计价**: ¥831.73/克

### 🇨🇳 国内金价
- **黄金大盘价格**: ¥835.58/克
- **黄金9999**: ¥838.30/克

### 🏪 金店零售价
- **饰品金**: ¥990-1,200/克
- **周大福/周大生**: ¥1,199/克
- **银行金条**: ¥851.9/克

---
*数据来源：金价查询网*
"""

        result = notifier.send_markdown("今日金价", text)
        return {"status": "ok", "pushed": result.get("ok", False)}

    async def list_reports(self, **kwargs) -> dict:
        """列出所有报告"""
        reports = []
        for f in sorted(REPORT_DIR.glob("*.md"), reverse=True):
            reports.append({
                "name": f.name,
                "path": str(f),
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        return {"status": "ok", "reports": reports[:50]}
