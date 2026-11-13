"""
TrendRadar 插件 - 包装调用原项目脚本
原项目: /root/.openclaw/workspace/trendradar/
GitHub: https://github.com/SANSAN0/TrendRadar
"""
import asyncio
import subprocess
import logging
from pathlib import Path
from econ_harness.core.plugin import BasePlugin
from econ_harness.core.notify import notifier

logger = logging.getLogger(__name__)

TREDDRAR_DIR = Path("/root/.openclaw/workspace/trendradar")


class TrendRadarPlugin(BasePlugin):
    name = "trendradar"
    version = "1.0.0"
    description = "热榜监控、关键词匹配、钉钉推送（包装调用原项目）"

    async def on_start(self):
        """检查原项目是否存在"""
        if not TREDDRAR_DIR.exists():
            self.error(f"TrendRadar 目录不存在: {TREDDRAR_DIR}")
            raise FileNotFoundError(f"TrendRadar not found at {TREDDRAR_DIR}")
        self.info(f"TrendRadar plugin started, using {TREDDRAR_DIR}")

    async def on_stop(self):
        self.info("TrendRadar plugin stopped")

    async def on_task(self, task_name: str, **kwargs):
        """处理任务"""
        tasks = {
            "monitor": self.run_monitor,
            "daily_report": self.run_daily_report,
            "push_summary": self.push_summary,
            "status": self.get_status,
        }
        handler = tasks.get(task_name)
        if handler:
            return await handler(**kwargs)
        return None

    async def run_monitor(self, **kwargs) -> dict:
        """运行 TrendRadar 增量监控"""
        self.info("Running TrendRadar monitor...")
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._run_script,
            str(TREDDRAR_DIR / "run_monitor.sh")
        )
        
        return self._parse_monitor_output(result)

    async def run_daily_report(self, **kwargs) -> dict:
        """运行日报生成"""
        self.info("Running daily report...")
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._run_script,
            str(TREDDRAR_DIR / "run_daily_report.sh")
        )
        
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "output": result.stdout[-500:] if result.stdout else "",
            "error": result.stderr[-200:] if result.stderr else "",
        }

    async def push_summary(self, **kwargs) -> dict:
        """推送摘要到钉钉"""
        title = kwargs.get("title", "TrendRadar 监控报告")
        summary = kwargs.get("summary", "暂无摘要")
        
        # 读取最新日志
        log_file = TREDDRAR_DIR / "output" / "monitor.log"
        if log_file.exists():
            with open(log_file) as f:
                lines = f.readlines()
                recent = "".join(lines[-20:])
        else:
            recent = "日志文件不存在"
        
        text = f"""## 📊 TrendRadar 监控报告

### 摘要
{summary}

### 最近日志
```
{recent}
```

---
*数据来源：TrendRadar*
"""
        
        return notifier.send_markdown(title, text)

    async def get_status(self, **kwargs) -> dict:
        """获取 TrendRadar 状态"""
        log_file = TREDDRAR_DIR / "output" / "monitor.log"
        
        status = {
            "installed": TREDDRAR_DIR.exists(),
            "version": "6.11.0",  # TODO: 动态读取
            "log_exists": log_file.exists(),
        }
        
        if log_file.exists():
            with open(log_file) as f:
                lines = f.readlines()
                status["last_lines"] = "".join(lines[-5:])
        
        return status

    def _run_script(self, script_path: str) -> subprocess.CompletedProcess:
        """执行脚本"""
        try:
            result = subprocess.run(
                ["bash", script_path],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(TREDDRAR_DIR)
            )
            return result
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args=[script_path],
                returncode=-1,
                stdout="",
                stderr="Timeout after 300s"
            )
        except Exception as e:
            return subprocess.CompletedProcess(
                args=[script_path],
                returncode=-1,
                stdout="",
                stderr=str(e)
            )

    def _parse_monitor_output(self, result: subprocess.CompletedProcess) -> dict:
        """解析监控输出"""
        output = result.stdout or ""
        
        # 提取关键信息
        parsed = {
            "status": "ok" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "platforms_ok": 0,
            "platforms_failed": 0,
            "new_news": 0,
            "matched": 0,
            "pushed": False,
        }
        
        # 解析平台状态
        if "成功:" in output:
            for line in output.split("\n"):
                if "成功:" in line:
                    parsed["platforms_ok"] = line.count("'") // 2
                if "失败:" in line:
                    parsed["platforms_failed"] = line.count("'") // 2
        
        # 解析新增数量
        if "新增" in output:
            import re
            match = re.search(r"新增\s*(\d+)\s*条", output)
            if match:
                parsed["new_news"] = int(match.group(1))
        
        # 解析命中数量
        if "命中" in output:
            import re
            match = re.search(r"(\d+)\s*条命中", output)
            if match:
                parsed["matched"] = int(match.group(1))
        
        # 是否推送
        parsed["pushed"] = "推送" in output and "钉钉" in output
        
        return parsed
