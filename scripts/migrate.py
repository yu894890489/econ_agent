"""迁移脚本 - 从旧系统迁移数据"""

import asyncio
import shutil
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


async def migrate_database():
    """迁移数据库"""
    source_dir = Path("/root/.openclaw/workspace/econ_agent")
    target_dir = Path("/root/.openclaw/workspace/econ-harness/data")
    
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 复制数据库文件
    db_files = [
        "econ_agent.db",
        "econ.db", 
        "portfolio.db",
    ]
    
    for db_file in db_files:
        source = source_dir / db_file
        if source.exists():
            target = target_dir / f"legacy_{db_file}"
            shutil.copy2(source, target)
            logger.info(f"Copied {source} -> {target}")
    
    # 复制 TrendRadar 数据
    trendradar_dir = Path("/root/.openclaw/workspace/trendradar/output")
    if trendradar_dir.exists():
        target_trendradar = target_dir / "trendradar"
        target_trendradar.mkdir(exist_ok=True)
        
        for db_file in trendradar_dir.glob("*.db"):
            target = target_trendradar / db_file.name
            shutil.copy2(db_file, target)
            logger.info(f"Copied {db_file} -> {target}")


async def migrate_config():
    """迁移配置文件"""
    source_dirs = [
        Path("/root/.openclaw/workspace/econ_agent/config"),
        Path("/root/.openclaw/workspace/trendradar/config"),
    ]
    
    target_dir = Path("/root/.openclaw/workspace/econ-harness/config/legacy")
    target_dir.mkdir(parents=True, exist_ok=True)
    
    for source_dir in source_dirs:
        if source_dir.exists():
            for config_file in source_dir.glob("*"):
                if config_file.is_file():
                    target = target_dir / f"{source_dir.name}_{config_file.name}"
                    shutil.copy2(config_file, target)
                    logger.info(f"Copied {config_file} -> {target}")


async def main():
    """主迁移流程"""
    logger.info("Starting migration...")
    
    await migrate_database()
    await migrate_config()
    
    logger.info("Migration completed!")
    logger.info("Next step: Run 'python -m econ_harness init' to initialize new database")


if __name__ == "__main__":
    asyncio.run(main())
