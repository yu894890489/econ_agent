"""插件基类和管理器"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


class BasePlugin(ABC):
    """插件基类"""
    
    name: str = "base_plugin"
    version: str = "1.0.0"
    description: str = ""
    
    def __init__(self, config: Dict[str, Any], db=None, event_bus=None):
        self.config = config
        self.db = db
        self.event_bus = event_bus
        self.enabled = True
    
    @abstractmethod
    async def on_start(self):
        """插件启动时调用"""
        pass
    
    @abstractmethod
    async def on_stop(self):
        """插件停止时调用"""
        pass
    
    @abstractmethod
    async def on_task(self, task_name: str, **kwargs) -> Any:
        """接收任务"""
        pass
    
    async def on_event(self, event_type: str, data: Any):
        """接收事件（可选）"""
        pass
    
    def log(self, level: str, message: str):
        """记录日志"""
        getattr(logger, level)(f"[{self.name}] {message}")
    
    def info(self, message: str):
        self.log("info", message)
    
    def warning(self, message: str):
        self.log("warning", message)
    
    def error(self, message: str):
        self.log("error", message)


class PluginManager:
    """插件管理器"""
    
    def __init__(self):
        self.plugins: Dict[str, BasePlugin] = {}
        self._running = False
    
    def register(self, plugin: BasePlugin):
        """注册插件"""
        self.plugins[plugin.name] = plugin
        logger.info(f"Registered plugin: {plugin.name} v{plugin.version}")
    
    def unregister(self, name: str):
        """注销插件"""
        if name in self.plugins:
            del self.plugins[name]
            logger.info(f"Unregistered plugin: {name}")
    
    async def start_all(self):
        """启动所有插件"""
        self._running = True
        for name, plugin in self.plugins.items():
            if plugin.enabled:
                try:
                    await plugin.on_start()
                    logger.info(f"Started plugin: {name}")
                except Exception as e:
                    logger.error(f"Failed to start plugin {name}: {e}")
    
    async def stop_all(self):
        """停止所有插件"""
        self._running = False
        for name, plugin in self.plugins.items():
            try:
                await plugin.on_stop()
                logger.info(f"Stopped plugin: {name}")
            except Exception as e:
                logger.error(f"Failed to stop plugin {name}: {e}")
    
    async def dispatch_task(self, task_name: str, **kwargs) -> Dict[str, Any]:
        """分发任务到所有插件"""
        results = {}
        for name, plugin in self.plugins.items():
            if plugin.enabled:
                try:
                    result = await plugin.on_task(task_name, **kwargs)
                    results[name] = {"status": "ok", "result": result}
                except Exception as e:
                    results[name] = {"status": "error", "error": str(e)}
        return results
    
    async def broadcast_event(self, event_type: str, data: Any):
        """广播事件到所有插件"""
        for name, plugin in self.plugins.items():
            if plugin.enabled:
                try:
                    await plugin.on_event(event_type, data)
                except Exception as e:
                    logger.error(f"Plugin {name} failed to handle event {event_type}: {e}")
    
    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """获取插件"""
        return self.plugins.get(name)
    
    def list_plugins(self) -> List[Dict[str, str]]:
        """列出所有插件"""
        return [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "enabled": p.enabled,
            }
            for p in self.plugins.values()
        ]
