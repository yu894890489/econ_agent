"""数据库测试"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from econ_harness.core.database import Database


@pytest.fixture
def temp_db():
    """创建临时数据库"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    yield db_path
    
    Path(db_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_database_init(temp_db):
    """测试数据库初始化"""
    db = Database(temp_db)
    
    await db.connect()
    await db.init_schema()
    
    # 验证表已创建
    tables = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    table_names = [t["name"] for t in tables]
    
    assert "raw_news" in table_names
    assert "signals" in table_names
    assert "portfolio" in table_names
    
    await db.close()


@pytest.mark.asyncio
async def test_database_crud(temp_db):
    """测试 CRUD 操作"""
    db = Database(temp_db)
    
    await db.connect()
    await db.init_schema()
    
    # Insert
    await db.execute(
        "INSERT INTO keywords (keyword, priority) VALUES (?, ?)",
        ("test", "P0")
    )
    
    # Select
    row = await db.fetch_one(
        "SELECT * FROM keywords WHERE keyword = ?",
        ("test",)
    )
    assert row is not None
    assert row["keyword"] == "test"
    assert row["priority"] == "P0"
    
    # Update
    await db.execute(
        "UPDATE keywords SET priority = ? WHERE keyword = ?",
        ("P1", "test")
    )
    
    row = await db.fetch_one(
        "SELECT * FROM keywords WHERE keyword = ?",
        ("test",)
    )
    assert row["priority"] == "P1"
    
    # Delete
    await db.execute(
        "DELETE FROM keywords WHERE keyword = ?",
        ("test",)
    )
    
    row = await db.fetch_one(
        "SELECT * FROM keywords WHERE keyword = ?",
        ("test",)
    )
    assert row is None
    
    await db.close()
