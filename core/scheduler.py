"""任务调度器"""

import asyncio
from typing import Callable, Dict, List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class Task:
    """任务定义"""
    
    def __init__(
        self,
        name: str,
        schedule: str,  # cron expression or interval like "30m", "1h"
        callback: Callable,
        enabled: bool = True,
        description: str = "",
    ):
        self.name = name
        self.schedule = schedule
        self.callback = callback
        self.enabled = enabled
        self.description = description
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.run_count = 0
        self.error_count = 0
    
    def calculate_next_run(self, now: datetime) -> datetime:
        """计算下次运行时间"""
        if self.schedule.endswith("m"):
            minutes = int(self.schedule[:-1])
            return now + timedelta(minutes=minutes)
        elif self.schedule.endswith("h"):
            hours = int(self.schedule[:-1])
            return now + timedelta(hours=hours)
        elif self.schedule.endswith("d"):
            days = int(self.schedule[:-1])
            return now + timedelta(days=days)
        else:
            # TODO: Parse cron expression
            return now + timedelta(hours=1)


class TaskScheduler:
    """任务调度器"""
    
    def __init__(self):
        self.tasks: Dict[str, Task] = {}
        self._running = False
    
    def add_task(self, task: Task):
        """添加任务"""
        self.tasks[task.name] = task
        logger.info(f"Added task: {task.name} (schedule: {task.schedule})")
    
    def remove_task(self, name: str):
        """移除任务"""
        if name in self.tasks:
            del self.tasks[name]
            logger.info(f"Removed task: {name}")
    
    def enable_task(self, name: str):
        """启用任务"""
        if name in self.tasks:
            self.tasks[name].enabled = True
    
    def disable_task(self, name: str):
        """禁用任务"""
        if name in self.tasks:
            self.tasks[name].enabled = False
    
    async def run_task(self, name: str):
        """手动运行任务"""
        if name not in self.tasks:
            raise ValueError(f"Task not found: {name}")
        
        task = self.tasks[name]
        try:
            logger.info(f"Running task: {name}")
            await task.callback()
            task.last_run = datetime.now()
            task.run_count += 1
            logger.info(f"Task completed: {name}")
        except Exception as e:
            task.error_count += 1
            logger.error(f"Task failed: {name} - {e}")
            raise
    
    async def _run_loop(self):
        """调度循环"""
        self._running = True
        while self._running:
            now = datetime.now()
            
            for name, task in self.tasks.items():
                if not task.enabled:
                    continue
                
                if task.next_run is None:
                    task.next_run = task.calculate_next_run(now)
                
                if now >= task.next_run:
                    try:
                        await self.run_task(name)
                        task.next_run = task.calculate_next_run(now)
                    except Exception as e:
                        logger.error(f"Task {name} failed: {e}")
            
            await asyncio.sleep(10)  # Check every 10 seconds
    
    async def start(self):
        """启动调度器"""
        self._running = True
        asyncio.create_task(self._run_loop())
        logger.info("Task scheduler started")
    
    async def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("Task scheduler stopped")
    
    def list_tasks(self) -> List[Dict]:
        """列出所有任务"""
        return [
            {
                "name": t.name,
                "schedule": t.schedule,
                "enabled": t.enabled,
                "last_run": t.last_run.isoformat() if t.last_run else None,
                "next_run": t.next_run.isoformat() if t.next_run else None,
                "run_count": t.run_count,
                "error_count": t.error_count,
            }
            for t in self.tasks.values()
        ]
