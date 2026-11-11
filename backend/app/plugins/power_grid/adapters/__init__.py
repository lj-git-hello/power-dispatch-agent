"""电网业务外部系统适配器（垂直插件私有）。

本目录内的实现体仅服务于电网检修调度业务：
- OMSGatewayAdapter：停电管理系统正式工单创建 / 状态同步
- SCADAGatewayAdapter：调度自动化系统许可令签发

通用底座（app/core/**、app/services/acl/**）只保留协议契约
（OrderAdapterProtocol / CredentialAdapterProtocol），不含任何业务实现，
以保证"AI 资产与业务物理隔离"。
"""

from app.plugins.power_grid.adapters.oms_adapter import OMSGatewayAdapter
from app.plugins.power_grid.adapters.scada_adapter import SCADAGatewayAdapter

__all__ = [
    "OMSGatewayAdapter",
    "SCADAGatewayAdapter",
]
