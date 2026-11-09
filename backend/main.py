"""FastAPI 应用全局主入口 —— 仅承载通用容器底座。

职责：
- Windows 事件循环策略；加载 .env
- Lifespan 双连接池生命周期（LangGraph checkpointer + 业务引擎）
- 中间件与模块化路由挂载（系统鉴权 / 电力业务 / 通用 RAG）

业务处理函数不在本文件内实现；业务端点位于各 APIRouter。
"""

import asyncio
import sys
from contextlib import asynccontextmanager

# Windows 兼容：checkpointer 链路含 psycopg，须在事件循环创建前切换策略
if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 加载 backend/.env
load_dotenv()

from app.core.database import async_engine, checkpointer_manager
from app.core.workflow import DEFAULT_GRAPH_NAME, GraphRegistry
from app.api.v1.auth import router as auth_router
from app.api.v1.knowledge import knowledge_router
from app.plugins.power_grid.graph import build_dispatch_graph
from app.plugins.power_grid.router import (
    power_dispatch_router,
)

# 全局状态机实例（lifespan 中构建并注册，绑定 Postgres checkpointer）
graph_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph_app
    # 启动：LangGraph 专属连接池 + 幂等建表（含 saver.setup()）
    await checkpointer_manager.init_pool()
    app.state.checkpointer = checkpointer_manager.saver
    # 构建电网插件图，并通过注册中心对通用底座暴露（依赖反转）
    graph_app = build_dispatch_graph(checkpointer_manager.saver)
    GraphRegistry.register_graph(DEFAULT_GRAPH_NAME, graph_app)
    print("[中枢就绪] 电网插件状态机已挂载并注册 + Checkpointer 连接池就绪")
    yield
    # 退出：先关检查点池，再释放业务引擎
    graph_app = None
    await checkpointer_manager.close_pool()
    await async_engine.dispose()
    print("[中枢关停] Checkpointer 池与业务引擎连接已释放")


app = FastAPI(
    title="企业级 AI Agent 通用脚手架（电力业务接入）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模块化路由装配
app.include_router(auth_router, prefix="/api/v1")
app.include_router(
    power_dispatch_router, prefix="/api/v1/power-dispatch"
)
app.include_router(knowledge_router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health_check() -> dict:
    """健康检查：网关存活与状态机挂载状态。"""
    return {
        "code": 200,
        "status": "ok",
        "graph_ready": graph_app is not None,
    }
