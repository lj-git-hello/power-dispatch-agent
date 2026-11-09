"""通用工作流运行态基石状态（跨业务、零业务词汇）。"""

from typing import TypedDict


class BaseWorkflowState(TypedDict):
    """所有垂直业务工作流状态的通用基类。

    仅承载跨业务通用的运行态字段；业务专属字段由各插件子类扩展。
    """

    # 引擎线程 ID
    thread_id: str
    # 前端会话 ID
    session_id: str
    # 发起人 ID
    user_id: str
    # 流程状态
    status: str
    # 异常信息（正常为 None）
    error: str | None
