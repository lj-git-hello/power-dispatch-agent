"""传统业务系统防腐层（Anti-Corruption Layer）。

隔离本系统与三类外部企业系统的交互，对外仅暴露防腐接口，内部为 Mock 实现：
- IAM：统一身份认证（JWT 签发 / 校验）
- OMS：停电管理系统（正式工单创建 / 状态同步）
- SCADA：调度自动化系统（调度许可令签发）
"""

from app.services.acl.iam_adapter import (
    MOCK_USERS,
    IAMGatewayAdapter,
    create_access_token,
    verify_access_token,
)
from app.services.acl.oms_adapter import OMSGatewayAdapter
from app.services.acl.protocols import (
    IAMAdapterProtocol,
    OMSGatewayAdapterProtocol,
    SCADAGatewayAdapterProtocol,
)
from app.services.acl.scada_adapter import SCADAGatewayAdapter

__all__ = [
    "MOCK_USERS",
    "IAMGatewayAdapter",
    "create_access_token",
    "verify_access_token",
    "OMSGatewayAdapter",
    "SCADAGatewayAdapter",
    "IAMAdapterProtocol",
    "OMSGatewayAdapterProtocol",
    "SCADAGatewayAdapterProtocol",
]