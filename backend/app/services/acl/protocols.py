"""防腐层标准抽象契约（PEP 544 typing.Protocol）。

以结构化子类型（structural subtyping）固化三类外部系统适配器必须满足的
接口契约，供依赖注入、静态类型检查与未来真实实现替换时校验。

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
class OMSGatewayAdapterProtocol(Protocol):
    """停电管理系统（OMS）网关适配器契约。"""

    async def create_official_order(
        self, draft_data: dict[str, Any], creator_id: str
    ) -> str:
        """创建正式工单，返回正式工单号。"""
        ...

    async def update_order_status(
        self,
        biz_order_id: str,
        new_status: str,
        audit_opinion: str | None = None,
    ) -> bool:
        """同步工单状态变更，返回是否成功。"""
        ...


@runtime_checkable
class SCADAGatewayAdapterProtocol(Protocol):
    """调度自动化（SCADA）网关适配器契约。"""

    async def issue_dispatch_permit(
        self, biz_order_id: str, reviewer_id: str
    ) -> dict[str, Any]:
        """签发调度许可令，返回许可令结构体。"""
        ...