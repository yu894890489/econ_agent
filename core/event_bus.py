"""事件总线"""

import asyncio
from typing import Any, Callable, Dict, List
import logging

logger = logging.getLogger(__name__)


class EventBus:
    """事件总线"""
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
    
    def subscribe(self, event_type: str, handler: Callable):
        """订阅事件"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed to event: {event_type}")
    
    def unsubscribe(self, event_type: str, handler: Callable):
        """取消订阅"""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]
    
    async def publish(self, event_type: str, data: Any = None):
        """发布事件"""
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    logger.error(f"Event handler failed for {event_type}: {e}")
    
    def clear(self, event_type: str = None):
        """清除事件处理器"""
        if event_type:
            self._handlers.pop(event_type, None)
        else:
            self._handlers.clear()
    
    def list_events(self) -> Dict[str, int]:
        """列出所有事件类型和处理器数量"""
        return {k: len(v) for k, v in self._handlers.items()}
