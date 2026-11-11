"""传统业务系统防腐层（Anti-Corruption Layer）—— 通用契约层。

隔离本系统与外部企业系统的交互，对外仅暴露防腐接口：
- IAM：统一身份认证（JWT 签发 / 校验）—— 跨业务通用，保留在本层
- 通用协议：OrderAdapterProtocol（业务单据）/ CredentialAdapterProtocol（凭证签章）

**物理隔离约束**：本包不得导入任何业务插件模块。业务专属适配器实现体
一律归属各自插件目录（app/plugins/<biz>/adapters/），
通用层只保留契约（Protocol），以保证 AI 资产与业务完全隔离。
"""

from app.services.acl.iam_adapter import (
    MOCK_USERS,
    IAMGatewayAdapter,
    create_access_token,
    verify_access_token,
)
from app.services.acl.protocols import (
    CredentialAdapterProtocol,
    IAMAdapterProtocol,
    OrderAdapterProtocol,
)

__all__ = [
    "MOCK_USERS",
    "IAMGatewayAdapter",
    "create_access_token",
    "verify_access_token",
    "IAMAdapterProtocol",
    "OrderAdapterProtocol",
    "CredentialAdapterProtocol",
]
