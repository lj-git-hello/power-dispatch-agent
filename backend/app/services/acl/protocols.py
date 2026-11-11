"""防腐层标准抽象契约（PEP 544 typing.Protocol）。

以结构化子类型（structural subtyping）固化外部系统适配器必须满足的
接口契约，供依赖注入、静态类型检查与未来真实实现替换时校验。

本模块只保留**跨业务通用**的契约，实现体全部归属各业务插件：
- IAMAdapterProtocol：统一身份认证（任何业务域均复用）
- OrderAdapterProtocol：业务单据系统（工单创建 / 状态同步）
- CredentialAdapterProtocol：凭证与防伪签章系统（票据 / 凭证签发）

实现方无需显式继承：只要方法签名与本协议一致，即被视为该协议的实现
（duck typing 的静态化）。
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IAMAdapterProtocol(Protocol):
    """统一身份认证适配器契约。"""

    def verify_token(self, token: str) -> dict[str, Any]:
        """校验访问令牌，返回解码后的声明字典。"""
        ...


@runtime_checkable
class OrderAdapterProtocol(Protocol):
    """业务单据系统适配器契约（正式工单建档 / 状态同步）。"""

    async def create_official_order(
        self, draft_data: dict[str, Any], creator_id: str
    ) -> str:
        """创建正式单据，返回单据号。"""
        ...

    async def update_order_status(
        self,
        biz_order_id: str,
        new_status: str,
        audit_opinion: str | None = None,
    ) -> bool:
        """同步单据状态变更，返回是否成功。"""
        ...


@runtime_checkable
class CredentialAdapterProtocol(Protocol):
    """凭证与防伪签章系统适配器契约（签发带 CA 签名的凭证）。"""

    async def issue_credential(
        self, biz_order_id: str, reviewer_id: str
    ) -> dict[str, Any]:
        """签发凭证，返回凭证结构体。"""
        ...
