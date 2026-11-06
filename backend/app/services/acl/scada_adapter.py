"""调度自动化防腐适配器（SCADA Anti-Corruption Adapter）。

模拟调度自动化系统（SCADA）签发具备法律效力的电网调度许可令。
后续替换为真实 SCADA / 调度主站接口时，仅替换本类内部实现，
对外保持 issue_dispatch_permit 签名不变。
"""

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---- 调度令格式常量（禁止魔法值） ----
PERMIT_PREFIX = "DISP"
PERMIT_DATE_FORMAT = "%Y%m%d"
PERMIT_SUFFIX_HEX_BYTES = 4  # 4 字节 -> 8 位 HEX 大写

PERMIT_STATUS = "PERMITTED"
# CA 签名中代表核准动作的固定片段
SIGNATURE_ACTION = "APPROVED"
SIGNATURE_SEPARATOR = "|"


class SCADAGatewayAdapter:
    """调度自动化网关防腐适配器（Mock 实现）。"""

    def issue_dispatch_permit(
        self, biz_order_id: str, reviewer_id: str
    ) -> dict[str, Any]:
        """模拟签发电网调度许可令。

        返回结构：permit_no（DISP-YYYYMMDD-后缀）、status=PERMITTED、
        ca_signature_hash（sha256 over permit_no|biz_order_id|reviewer_id|APPROVED）、
        issued_at。
        """
        today = datetime.now(timezone.utc).strftime(PERMIT_DATE_FORMAT)
        suffix = secrets.token_hex(PERMIT_SUFFIX_HEX_BYTES).upper()
        permit_no = f"{PERMIT_PREFIX}-{today}-{suffix}"

        issued_at = datetime.now(timezone.utc).isoformat()

        signature_source = SIGNATURE_SEPARATOR.join(
            [permit_no, biz_order_id, reviewer_id, SIGNATURE_ACTION]
        )
        ca_signature_hash = hashlib.sha256(
            signature_source.encode("utf-8")
        ).hexdigest()

        logger.info(
            "[SCADA-Mock] 调度许可令已签发 permit_no=%s biz_order_id=%s "
            "reviewer_id=%s status=%s",
            permit_no,
            biz_order_id,
            reviewer_id,
            PERMIT_STATUS,
        )

        return {
            "permit_no": permit_no,
            "status": PERMIT_STATUS,
            "ca_signature_hash": ca_signature_hash,
            "issued_at": issued_at,
        }
