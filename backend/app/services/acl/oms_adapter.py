"""停电管理系统防腐适配器（OMS Anti-Corruption Adapter）。

模拟企业 OMS（Outage Management System）正式工单接口。
后续替换为真实 OMS HTTP / ESB 调用时，仅替换本类内部实现，
对外保持 create_official_order / update_order_status 签名不变。
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---- 工单格式常量（禁止魔法值） ----
ORDER_PREFIX = "OMS"
ORDER_DATE_FORMAT = "%Y%m%d"
ORDER_RANDOM_DIGITS = 6
ORDER_RANDOM_UPPER_BOUND = 10**ORDER_RANDOM_DIGITS

# OMS 工单内部状态（与本系统状态机解耦，仅做镜像）
DEFAULT_INITIAL_STATUS = "RECEIVED"


class OMSGatewayAdapter:
    """企业 OMS 网关防腐适配器（Mock 实现）。"""

    def create_official_order(self, draft_data: dict[str, Any], creator_id: str) -> str:
        """模拟 OMS 正式工单建档，返回原子自增格式工单号。

        格式：OMS-YYYYMMDD-六位随机数，如 OMS-20261106-048213。
        """
        today = datetime.now(timezone.utc).strftime(ORDER_DATE_FORMAT)
        serial = f"{secrets.randbelow(ORDER_RANDOM_UPPER_BOUND):0{ORDER_RANDOM_DIGITS}d}"
        biz_order_id = f"{ORDER_PREFIX}-{today}-{serial}"

        logger.info(
            "[OMS-Mock] 正式工单已创建 biz_order_id=%s creator_id=%s "
            "substation=%s voltage_level=%s initial_status=%s",
            biz_order_id,
            creator_id,
            draft_data.get("substation_name"),
            draft_data.get("voltage_level"),
            DEFAULT_INITIAL_STATUS,
        )
        return biz_order_id

    def update_order_status(
        self,
        biz_order_id: str,
        new_status: str,
        audit_opinion: str | None = None,
    ) -> bool:
        """模拟同步变更 OMS 工单状态，记录审核意见并返回成功。"""
        logger.info(
            "[OMS-Mock] 工单状态同步 biz_order_id=%s new_status=%s audit_opinion=%s",
            biz_order_id,
            new_status,
            audit_opinion,
        )
        return True
