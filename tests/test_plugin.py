"""插件系统测试"""

import pytest
import asyncio
from econ_harness.core.plugin import BasePlugin, PluginManager


class MockPlugin(BasePlugin):
    name = "mock"
    version = "1.0.0"
    description = "Mock plugin for testing"
    
    def __init__(self):
        super().__init__({}, None, None)
        self.started = False
        self.stopped = False
        self.tasks = []
    
    async def on_start(self):
        self.started = True
    
    async def on_stop(self):
        self.stopped = True
    
    async def on_task(self, task_name: str, **kwargs):
        self.tasks.append(task_name)
        return {"task": task_name}


@pytest.mark.asyncio
async def test_plugin_lifecycle():
    """测试插件生命周期"""
    plugin = MockPlugin()
    
    await plugin.on_start()
    assert plugin.started is True
    
    result = await plugin.on_task("test_task")
    assert result["task"] == "test_task"
    assert "test_task" in plugin.tasks
    
    await plugin.on_stop()
    assert plugin.stopped is True


@pytest.mark.asyncio
async def test_plugin_manager():
    """测试插件管理器"""
    manager = PluginManager()
    
    plugin1 = MockPlugin()
    plugin2 = MockPlugin()
    plugin2.name = "mock2"
    
    manager.register(plugin1)
    manager.register(plugin2)
    
    assert len(manager.plugins) == 2
    
    await manager.start_all()
    assert plugin1.started is True
    assert plugin2.started is True
    
    results = await manager.dispatch_task("test")
    assert "mock" in results
    assert "mock2" in results
    
    await manager.stop_all()
    assert plugin1.stopped is True
    assert plugin2.stopped is True


@pytest.mark.asyncio
async def test_plugin_disable():
    """测试禁用插件"""
    manager = PluginManager()
    
    plugin = MockPlugin()
    plugin.enabled = False
    
    manager.register(plugin)
    
    await manager.start_all()
    assert plugin.started is False  # 禁用插件不应启动
    
    results = await manager.dispatch_task("test")
    assert "mock" not in results  # 禁用插件不应接收任务
