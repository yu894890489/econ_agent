"""
Portfolio 插件 - 模拟交易引擎
从 econ_agent/core/portfolio.py 提取，独立运行
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


class PortfolioPlugin(BasePlugin):
    name = "portfolio"
    version = "1.0.0"
    description = "模拟交易、净值计算、止损检查、持仓报告"

    async def on_start(self):
        from core.db import init_db
        init_db()
        self.info("Portfolio plugin started")

    async def on_stop(self):
        self.info("Portfolio plugin stopped")

    async def on_task(self, task_name: str, **kwargs):
        tasks = {
            "nav": self.get_nav,
            "positions": self.get_positions,
            "snapshot": self.snapshot,
            "execute_signal": self.execute_signal,
            "close_position": self.close_position,
            "trade_stats": self.trade_stats,
            "check_stop_loss": self.check_stop_loss,
            "push_report": self.push_report,
        }
        handler = tasks.get(task_name)
        if handler:
            return await handler(**kwargs)
        return None

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

    async def snapshot(self, note: str = "", **kwargs) -> dict:
        """每日快照"""
        from core.db import get_conn
        from core import portfolio

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            n = portfolio.snapshot(conn, note=note)
            conn.close()
            return n

        nav_data = await loop.run_in_executor(None, _run)
        return {"status": "ok", **nav_data}

    async def execute_signal(self, signal_id: int, **kwargs) -> dict:
        """执行信号"""
        from core.db import get_conn
        from core import portfolio

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            result = portfolio.execute_signal(conn, signal_id)
            conn.close()
            return result

        result = await loop.run_in_executor(None, _run)
        return result

    async def close_position(self, symbol: str, **kwargs) -> dict:
        """平仓"""
        from core.db import get_conn
        from core import portfolio

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            result = portfolio.close_position(conn, symbol)
            conn.close()
            return result

        result = await loop.run_in_executor(None, _run)
        return result

    async def trade_stats(self, days: int = 30, **kwargs) -> dict:
        """交易统计"""
        from core.db import get_conn
        from core import portfolio

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            stats = portfolio.closed_trades_stats(conn, days)
            conn.close()
            return stats

        stats = await loop.run_in_executor(None, _run)
        return {"status": "ok", **stats}

    async def check_stop_loss(self, threshold: float = -0.08, **kwargs) -> dict:
        """止损检查"""
        from core.db import get_conn
        from core import portfolio

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            pos = portfolio.positions_report(conn)
            conn.close()
            alerts = []
            for p in pos:
                if p["pnl_pct"] / 100 <= threshold:
                    alerts.append({
                        "symbol": p["symbol"],
                        "name": p["name"],
                        "pnl_pct": p["pnl_pct"],
                        "avg_cost": p["avg_cost"],
                        "price": p["price"],
                    })
            return alerts

        alerts = await loop.run_in_executor(None, _run)
        return {"status": "ok", "stop_loss_alerts": alerts}

    async def push_report(self, **kwargs) -> dict:
        """推送持仓报告到钉钉"""
        from core.db import get_conn
        from core import portfolio

        loop = asyncio.get_event_loop()

        def _run():
            conn = get_conn()
            n = portfolio.nav(conn)
            pos = portfolio.positions_report(conn)
            stats = portfolio.closed_trades_stats(conn, 30)
            conn.close()
            return n, pos, stats

        n, pos, stats = await loop.run_in_executor(None, _run)

        lines = [
            f"**净值** ¥{n['nav']:,.0f}（{n['pnl_pct']:+.2f}%）",
            f"现金 ¥{n['cash']:,.0f} | 市值 ¥{n['market_value']:,.0f}",
        ]

        if pos:
            lines.append("\n**持仓**")
            for p in pos:
                emoji = "🟢" if p["pnl"] >= 0 else "🔴"
                lines.append(
                    f"{emoji} {p['name']}({p['symbol']}) "
                    f"成本{p['avg_cost']:.2f} 现价{p['price']:.2f} "
                    f"盈亏{p['pnl_pct']:+.1f}%"
                )
        else:
            lines.append("\n持仓：空仓")

        if stats["trades"]:
            lines.append(
                f"\n**近30日** {stats['trades']}笔 | "
                f"胜率{stats['win_rate']:.0f}% | 盈亏¥{stats['pnl']:,.0f}"
            )

        text = "\n".join(lines)
        result = notifier.send_markdown("持仓日报", text)
        return {"status": "ok", "pushed": result.get("ok", False)}
