import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def _require_env(key: str) -> str:
    """读取必需的环境变量；缺失即 fail-fast。

    严禁为口令类变量提供兜底默认值 —— 缺失应让进程启动失败并给出明确提示，
    而不是静默使用弱口令连接生产库。
    """
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"缺少必需的环境变量 {key}：请在 backend/.env 中配置后重启。"
        )
    return value


# 1. 连接基础配置
DB_USER = _require_env("DB_USER")
DB_PASSWORD = _require_env("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = _require_env("DB_NAME")

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