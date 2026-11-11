"""A2UI 通用聚合网关契约（跨业务、行业中立）。

本模块定义 Generative UI 网关的**协议层**内容：SSE 事件类型、
对话请求体、扁平事件负载。业务专属枚举一律归属各自插件的 schemas 模块。

对应端点：POST /api/v1/agent/chat-stream
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class A2UIEventType(str, Enum):
    """A2UI 聚合网关扁平事件类型（顶层字段平铺）。"""

    TOKEN = "token"       # LLM 增量 Token：{"type": "token", "content": ...}
    UI_CARD = "ui_card"   # 结构化卡片：{"type": "ui_card", "card_type": ..., "data": {...}}
    ERROR = "error"       # 异常降级：{"type": "error", "message": ...}
    DONE = "done"         # 终结信号：{"type": "done"}


class AgentChatRequest(BaseModel):
    """双模智能体对话入口请求体（知识问答 + 业务申报审批共用）。"""

    thread_id: str = Field(
        ...,
        description="会话线程 ID（Checkpointer 持久化键，多轮上下文以此隔离）",
        json_schema_extra={"example": "chat_thread_0001"},
    )
    session_id: str = Field(
        default="",
        description="前端 UI 会话 ID；用于把对话线程回挂到会话集合",
        json_schema_extra={
            "example": "6f1c9b0e-0f0a-4b0a-9f2e-2f0c1b2d3e4f"
        },
    )
    message: str = Field(
        default="",
        description="用户输入文本；卡片操作回传（分支 B）可缺省",
        json_schema_extra={
            "example": "办理第一种工作票时，工作负责人应履行哪些安全职责？"
        },
    )
    action_payload: Optional[dict[str, Any]] = Field(
        None,
        description="前端卡片操作回传载荷，如 {'decision': 'APPROVED', 'opinion': '安措完备'}；"
                    "兼容 {'action': 'approve'/'reject'} 旧格式",
        json_schema_extra={
            "example": {
                "decision": "APPROVED",
                "opinion": "潮流校核通过，安措完备",
            }
        },
    )


class AgentChatEvent(BaseModel):
    """扁平事件负载（SSE `data:` 的 JSON 结构）。

    字段随事件类型变化：
    - token：content 承载增量文本
    - ui_card：card_type 承载卡片类型，data 承载卡片结构体
    - error：message 承载错误描述
    - done：全部字段可缺省
    """

    type: A2UIEventType
    content: Optional[str] = None
    card_type: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    message: Optional[str] = None


__all__ = [
    "A2UIEventType",
    "AgentChatRequest",
    "AgentChatEvent",
]
