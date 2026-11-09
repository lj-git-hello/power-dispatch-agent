"""电网检修调度垂直业务状态。"""

from app.core.workflow import BaseWorkflowState


class DispatchState(BaseWorkflowState):
    """检修调度状态：在通用基石上扩展电网业务字段。"""

    # 检修要素
    substation: str
    voltage_level: str
    operation_task: str
    # 现场安措
    safety_measures: list[str]
    # 安规校验违规项
    violations: list[str]
    # OMS 正式工单号
    biz_order_id: str | None
    # 调度长审核结果
    audit_decision: dict | None
    # SCADA 调度令凭证
    permit_info: dict | None
