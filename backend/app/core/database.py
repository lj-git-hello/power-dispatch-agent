import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

# 1. 连接基础配置
DB_USER = os.getenv("DB_USER", "ai_admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ai_secure_password_2026")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "power_dispatch_ai")

# 业务连接串 (SQLAlchemy + asyncpg)
ASYNC_DB_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
# LangGraph Checkpointer 连接串 (psycopg 原生格式)
PSYCOPG_DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 2. 业务 & 向量专享连接池 (SQLAlchemy AsyncEngine)
async_engine = create_async_engine(
    ASYNC_DB_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=True
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入使用的数据库 Session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# 3. LangGraph Checkpointer 专属连接池与持久化管理器
class CheckpointerManager:
    """管理 LangGraph 检查点连接池生命周期与表初始化"""
    def __init__(self, conn_string: str):
        self.conn_string = conn_string
        self.pool: AsyncConnectionPool | None = None
        self.saver: AsyncPostgresSaver | None = None

    async def init_pool(self):
        # 建立独立连接池，防止与业务大事务/向量索引查询产生死锁
        self.pool = AsyncConnectionPool(
            conninfo=self.conn_string,
            min_size=2,
            max_size=10,
            open=False,
            kwargs={"autocommit": True}
        )
        await self.pool.open()
        
        # 实例化 AsyncPostgresSaver 并执行自动建表（checkpoints, checkpoint_blobs, checkpoint_writes）
        self.saver = AsyncPostgresSaver(self.pool)
        await self.saver.setup()

    async def close_pool(self):
        if self.pool:
            await self.pool.close()

checkpointer_manager = CheckpointerManager(PSYCOPG_DB_URL)