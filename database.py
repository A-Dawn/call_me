import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import MetaData
from sqlalchemy.ext.declarative import declarative_base

# 数据库文件路径 (独立数据库)
DB_PATH = os.path.join(os.path.dirname(__file__), "call_me.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# SQLAlchemy 基础设置
metadata = MetaData()
Base = declarative_base(metadata=metadata)

# 引擎与会话工厂
engine = None
AsyncSessionLocal = None

async def init_db():
    """初始化数据库连接"""
    global engine, AsyncSessionLocal
    
    if engine is None:
        engine = create_async_engine(
            DATABASE_URL,
            echo=False,  # 设置为 True 可查看 SQL 日志
            future=True,
            connect_args={"check_same_thread": False} # SQLite 必需
        )
        
        AsyncSessionLocal = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        
        # 自动建表
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

async def close_db():
    """关闭数据库连接"""
    global engine
    if engine:
        await engine.dispose()
        engine = None

async def get_db_session() -> AsyncSession:
    """获取数据库会话 (Dependency)"""
    if AsyncSessionLocal is None:
        await init_db()
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
