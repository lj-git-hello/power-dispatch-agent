"""FastAPI 应用全局主入口 —— 仅承载通用容器底座。

职责：
- Windows 事件循环策略；加载 .env
- 业务插件装配（目录扫描 + ACTIVE_PLUGIN 显式指定，换业务零改动）
- Lifespan 双连接池生命周期（LangGraph checkpointer + 业务引擎）
- 中间件与模块化路由挂载（系统鉴权 / 通用 RAG / 通用对话 / 插件清单 / 业务插件）

本文件不含任何业务词汇：接入哪个业务、端点在哪、状态机叫什么，
全部由 app/plugins/<biz>/plugin.py 的清单声明。
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Windows 兼容：checkpointer 链路含 psycopg，须在事件循环创建前切换策略
if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 加载 backend/.env（按绝对路径定位，不依赖进程工作目录）
load_dotenv(Path(__file__).resolve().parent / ".env")

from app.core.database import async_engine, checkpointer_manager
from app.core.plugin.loader import PluginLoader
from app.core.workflow import GraphRegistry
from app.api.v1.agent import agent_router
from app.api.v1.auth import router as auth_router
from app.api.v1.knowledge import knowledge_router
from app.api.v1.plugin import plugin_router

# 生效业务插件：模块级装载 —— 插件契约违规 / 生效插件无法确定时启动即失败
active_plugin = PluginLoader.load_active()

# 全局状态机实例（lifespan 中构建并注册，绑定 Postgres checkpointer）
graph_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph_app
    # 启动：LangGraph 专属连接池 + 幂等建表（含 saver.setup()）
    await checkpointer_manager.init_pool()
    app.state.checkpointer = checkpointer_manager.saver
    # 构建插件状态机，按插件名注册进注册中心
    # （不占用 DEFAULT 槽位：DEFAULT 属通用层，业务图漏传 graph_name 时
    #   应快速失败而非静默唤醒另一业务的图）
    if active_plugin.graph_factory is not None:
        graph_app = active_plugin.graph_factory(checkpointer_manager.saver)
        GraphRegistry.register_graph(active_plugin.graph_name, graph_app)
    print(
        f"[中枢就绪] 业务插件 {active_plugin.name} v{active_plugin.version} "
        f"已挂载（状态图：{active_plugin.graph_name or '无'}）"
        " + Checkpointer 连接池就绪"
    )
    yield
    # 退出：先关检查点池，再释放业务引擎
    graph_app = None
    await checkpointer_manager.close_pool()
    await async_engine.dispose()
    print("[中枢关停] Checkpointer 池与业务引擎连接已释放")


app = FastAPI(
    title="企业级 AI Agent 通用脚手架",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 通用路由（与业务无关） ----
app.include_router(auth_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(plugin_router, prefix="/api/v1")

# ---- 业务插件路由（按插件清单声明的前缀挂载） ----
app.include_router(active_plugin.router, prefix=active_plugin.router_prefix)


@app.get("/api/v1/health")
async def health_check() -> dict:
    """健康检查：网关存活与状态机挂载状态。"""
    return {
        "code": 200,
        "status": "ok",
        "plugin": active_plugin.name,
        "graph_ready": graph_app is not None,
    }
