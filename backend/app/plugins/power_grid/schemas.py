"""电网检修调度业务契约（垂直插件私有）。

仅存放电网业务专属枚举、请求体与卡片类型常量；
通用 A2UI 协议位于 app/schemas/a2ui.py，二者严格分离。
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 卡片类型常量（对齐后端实际下发的 wire 协议）
# ---------------------------------------------------------------------------
POWER_CARD_TYPE_DISPATCHER_AUDIT = "dispatcher_audit"
POWER_CARD_TYPE_PERMIT_RESULT = "permit_result"


class PermitAction(str, Enum):
    """调度核准卡片回传的操作类型。"""

    APPROVE = "approve"
    REJECT = "reject"


class DispatcherDecision(str, Enum):
    """调度长审核决定。"""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# 前端 action_payload 中审核决定的别名归一映射（大小写不敏感）
DISPATCHER_DECISION_ALIASES: dict[str, DispatcherDecision] = {
    "approved": DispatcherDecision.APPROVED,
    "approve": DispatcherDecision.APPROVED,
    "true": DispatcherDecision.APPROVED,
    "rejected": DispatcherDecision.REJECTED,
    "reject": DispatcherDecision.REJECTED,
    "false": DispatcherDecision.REJECTED,
}


class PlanApplyRequest(BaseModel):
    """检修计划提报请求体。"""

    plan_id: str = Field(..., description="检修计划唯一单号", example="PLAN_110KV_001")
    substation_name: str = Field(..., description="变电站名称", example="110kV 舜耕变电站")
    voltage_level: str = Field(..., description="电压等级", example="110kV")
    work_content: str = Field(..., description="检修作业内容", example="1号主变套管消缺")
    safety_measures: str = Field(..., description="安措预案", example="两票三制已准备，已悬挂接地线")


class PermitRequest(BaseModel):
    """调度许可核准请求体。"""

    plan_id: str = Field(..., description="检修计划单号", example="PLAN_110KV_001")
    permitted: bool = Field(..., description="是否核准签发", example=True)


__all__ = [
    "POWER_CARD_TYPE_DISPATCHER_AUDIT",
    "POWER_CARD_TYPE_PERMIT_RESULT",
    "PermitAction",
    "DispatcherDecision",
    "DISPATCHER_DECISION_ALIASES",
    "PlanApplyRequest",
    "PermitRequest",
]
