"""快速开始示例"""

import asyncio
from econ_harness.core.config import Config
from econ_harness.core.database import Database
from econ_harness.core.plugin import PluginManager
from econ_harness.plugins.trendradar import TrendRadarPlugin


async def main():
    # 1. 加载配置
    config = Config("config/settings.yaml")
    config.load()
    
    # 2. 连接数据库
    db = Database(config.get("database.path", "./data/econ_harness.db"))
    await db.connect()
    await db.init_schema()
    
    # 3. 创建插件管理器
    manager = PluginManager()
    
    # 4. 注册插件
    trendradar = TrendRadarPlugin(
        config=config.get("trendradar", {}),
        db=db,
    )
    manager.register(trendradar)
    
    # 5. 启动所有插件
    await manager.start_all()
    
    # 6. 运行任务
    results = await manager.dispatch_task("monitor")
    print(f"Task results: {results}")
    
    # 7. 停止所有插件
    await manager.stop_all()
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
