from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# A2UI 卡片与事件枚举（Generative UI 前端渲染路由契约）
# ============================================================
class CardType(str, Enum):
    """智能体下发的前端卡片类型"""
    RISK_AUDIT = "risk_audit"    # 安规初审报告卡（申报要素 + 风险定级 + 初审意见）
    APPROVAL = "approval"        # 调度长人工核准卡（批准 / 驳回操作按钮）
    PERMIT = "permit"            # 正式调度许可令卡
    REJECTED = "rejected"        # 驳回结论卡


class SSEEventType(str, Enum):
    """SSE 流式事件类型"""
    TOKEN = "token"                       # LLM 增量 Token
    INTENT = "intent"                     # 意图研判结果
    CARD = "card"                         # A2UI 结构化卡片
    WORKFLOW_INTERRUPT = "workflow_interrupt"  # 人机协同熔断挂起信号
    DONE = "done"                         # 单轮执行收口
    ERROR = "error"                       # 异常降级事件


class PermitAction(str, Enum):
    """调度核准卡片回传的操作类型"""
    APPROVE = "approve"
    REJECT = "reject"


# ============================================================
# 请求契约
# ============================================================
class AgentChatRequest(BaseModel):
    """双模智能体对话入口请求体（安规问答 + 业务申报审批共用）"""
    thread_id: str = Field(
        ...,
        description="会话线程 ID（Checkpointer 持久化键，多轮上下文以此隔离）",
        example="chat_thread_0001",
    )
    message: str = Field(
        ...,
        description="用户输入文本",
        example="办理第一种工作票时，工作负责人应履行哪些安全职责？",
    )
    action_payload: Optional[dict[str, Any]] = Field(
        None,
        description="前端卡片操作回传载荷，如 {'action': 'approve'} / {'action': 'reject'}",
        example={"action": "approve"},
    )


class PlanApplyRequest(BaseModel):
    plan_id: str = Field(..., description="检修计划唯一单号", example="PLAN_110KV_001")
    substation_name: str = Field(..., description="变电站名称", example="110kV 舜耕变电站")
    voltage_level: str = Field(..., description="电压等级", example="110kV")
    work_content: str = Field(..., description="检修作业内容", example="1号主变套管消缺")
    safety_measures: str = Field(..., description="安措预案", example="两票三制已准备，已悬挂接地线")


class PermitRequest(BaseModel):
    plan_id: str = Field(..., description="检修计划单号", example="PLAN_110KV_001")
    permitted: bool = Field(..., description="是否核准签发", example=True)
