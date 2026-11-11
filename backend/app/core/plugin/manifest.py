"""业务插件清单契约（通用层，零业务词汇）。

PluginManifest 是"插件自描述"的唯一载体：插件在自身目录内声明路由、
状态机工厂、对话能力与端点路径；通用底座据此完成装配，无需感知任何
业务语义，从而实现"接入新业务 = 新增一个插件目录"。

物理隔离约束：本模块不得出现任何垂直业务词汇（单据编号规则、业务角色、
卡片类型等均属插件私有）。
"""

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import APIRouter

from app.schemas.a2ui import AgentChatEvent, AgentChatRequest

# 网关统一前缀（与前端 http baseURL 对齐）
API_PREFIX = "/api"

# ---- 端点逻辑名（插件声明与前端消费的稳定契约） ----
ENDPOINT_TASKS = "tasks"        # 待办列表
ENDPOINT_MESSAGES = "messages"  # 线程消息
ENDPOINT_RESUME = "resume"      # 恢复 / 审批
ENDPOINT_APPLY = "apply"        # 业务提报

# ---- 通用角色占位（业务语义由各插件解释） ----
ROLE_SYSTEM = "SYSTEM"


class PluginContractError(RuntimeError):
    """插件契约违规（清单缺失 / 字段非法 / 生效插件无法确定）。"""


class TraceSink(Protocol):
    """运行留痕写入契约。

    通用对话网关据此把节点级 Token / 成本 / 时延写入 ai_execution_traces；
    写入动作完全由通用层实现，插件只负责上报观测数据。
    """

    async def record(
        self,
        node_name: str,
        model_name: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        total_cost: float = 0.0,
        tool_calls: dict[str, Any] | None = None,
        error_log: str | None = None,
    ) -> None:
        """记录一次节点级执行留痕。"""
        ...


@dataclass(frozen=True)
class ChatContext:
    """通用对话上下文（零业务语义）。"""

    # 物理线程 ID（通用层已加命名空间前缀）
    thread_id: str
    # 前端 UI 会话 ID
    session_id: str
    # 发起人 ID
    user_id: str
    # 发起人角色（IAM 层角色）
    user_role: str
    # 运行留痕写入器（通用层实现）
    trace_sink: TraceSink | None = None


class ChatHandler(Protocol):
    """插件对话能力契约：异步产出扁平 A2UI 事件。

    实现方为业务插件（如行业知识问答）；通用层负责 SSE 分帧、落库、
    错误收口与留痕，插件只负责语义。
    """

    def __call__(
        self, context: ChatContext, request: AgentChatRequest
    ) -> AsyncIterator[AgentChatEvent]:
        """产出事件流。"""
        ...


# 状态机工厂：入参为 checkpointer，出参为已编译图
GraphFactory = Callable[[Any], Any]


@dataclass(frozen=True)
class PluginIdentity:
    """插件声明的演示身份。

    通用 IAM 只维护"账号目录"，不解释角色语义；角色字符串由插件自定义，
    通用外壳的身份切换器据此渲染，底座不写死任何业务角色名。
    """

    # 登录账号 ID
    user_id: str
    # 展示名
    name: str
    # 角色标识（语义由插件解释）
    role: str
    # 部门 / 班组（可缺省）
    dept: str = ""


@dataclass(frozen=True)
class PluginManifest:
    """插件自描述清单。"""

    # 插件唯一名（与前端插件目录名一致）
    name: str
    # 插件语义化版本（前后端版本偏斜检测用）
    version: str
    # 插件路由（自身不带前缀，由通用层按 router_prefix 挂载）
    router: APIRouter
    # 路由挂载前缀（含 /api）
    router_prefix: str
    # 状态机工厂（可缺省：纯问答型插件无需状态机）
    graph_factory: GraphFactory | None = None
    # 状态机注册名（GraphRegistry 的键，必须显式传名以避免唤醒错图）
    graph_name: str = ""
    # 对话能力（可缺省：未接入对话时通用层返回明确 error 而非 500）
    chat_handler: ChatHandler | None = None
    # 端点路径（相对 router_prefix，如 {"tasks": "/tasks"}）
    endpoint_paths: Mapping[str, str] = field(default_factory=dict)
    # 演示身份（供通用外壳身份切换器 + Mock IAM 账号目录；可缺省）
    identities: tuple[PluginIdentity, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise PluginContractError("插件清单缺少 name。")
        if not self.version:
            raise PluginContractError(f"插件 {self.name} 缺少 version。")
        if not self.router_prefix.startswith(API_PREFIX):
            raise PluginContractError(
                f"插件 {self.name} 的 router_prefix={self.router_prefix!r} "
                f"必须以 {API_PREFIX!r} 开头。"
            )
        if self.graph_factory is not None and not self.graph_name:
            raise PluginContractError(
                f"插件 {self.name} 声明了 graph_factory，必须同时给出 graph_name。"
            )

    @property
    def endpoints(self) -> dict[str, str]:
        """端点绝对路径（相对 /api，与前端 http baseURL 对齐）。

        例：router_prefix=/api/v1/sample-biz + {"tasks": "/tasks"}
            → "/v1/sample-biz/tasks"
        """
        base = self.router_prefix.removeprefix(API_PREFIX).rstrip("/")
        resolved: dict[str, str] = {}
        for key, path in self.endpoint_paths.items():
            relative = path if path.startswith("/") else f"/{path}"
            resolved[key] = f"{base}{relative}"
        return resolved


__all__ = [
    "API_PREFIX",
    "ROLE_SYSTEM",
    "ENDPOINT_APPLY",
    "ENDPOINT_MESSAGES",
    "ENDPOINT_RESUME",
    "ENDPOINT_TASKS",
    "ChatContext",
    "ChatHandler",
    "GraphFactory",
    "PluginContractError",
    "PluginIdentity",
    "PluginManifest",
    "TraceSink",
]
