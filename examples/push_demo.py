"""
示例：推送分析结果到钉钉
"""
import asyncio
from econ_harness.core.config import Config
from econ_harness.core.database import Database
from econ_harness.core.plugin import PluginManager
from econ_harness.plugins.trendradar import TrendRadarPlugin
from econ_harness.plugins.econ_agent import EconAgentPlugin


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
    
    econ_agent = EconAgentPlugin(
        config=config.get("econ_agent", {}),
        db=db,
    )
    
    manager.register(trendradar)
    manager.register(econ_agent)
    
    # 5. 启动所有插件
    await manager.start_all()
    
    # 6. 推送 TrendRadar 摘要
    print("推送 TrendRadar 摘要...")
    result = await manager.dispatch_task(
        "push_summary",
        title="TrendRadar 实时监控",
        summary="今日监控到 150 条新闻，5 条命中关键词"
    )
    print(f"结果: {result}")
    
    # 7. 推送晨报
    print("\n推送晨报...")
    result = await manager.dispatch_task("morning_report")
    print(f"结果: {result}")
    
    # 8. 推送收盘报告
    print("\n推送收盘报告...")
    result = await manager.dispatch_task("evening_snapshot")
    print(f"结果: {result}")
    
    # 9. 停止所有插件
    await manager.stop_all()
    await db.close()
    
    print("\n✅ 所有推送完成！")


if __name__ == "__main__":
    asyncio.run(main())
