"""电力垂直业务路由 —— 检修调度（与通用脚手架物理隔离）。

本模块承载电力业务专属端点；通用底盘（鉴权 / 生命周期 / 中间件）
不感知任何电力概念。
"""

from fastapi import APIRouter, Depends

from app.core.security import require_roles

router = APIRouter(prefix="/power/dispatch", tags=["Power-Dispatch-Business"])

# 待审工单池（Mock 数据，后续替换为 OMS / 持久化查询）
_PENDING_POOL: list[dict] = [
    {
        "plan_id": "PLAN_20261106_001",
        "substation_name": "腊山变电站",
        "voltage_level": "220kV",
        "work_content": "220kV 腊山线 126 开关例行检修",
        "risk_level": "HIGH",
        "status": "WAITING_DISPATCHER_REVIEW",
        "creator_id": "applicant_01",
    },
    {
        "plan_id": "PLAN_20261106_002",
        "substation_name": "玉皇顶变电站",
        "voltage_level": "10kV",
        "work_content": "10kV 玉#5 配网线路消缺",
        "risk_level": "LOW",
        "status": "WAITING_DISPATCHER_REVIEW",
        "creator_id": "applicant_02",
    },
]


@router.get("/pool")
async def get_pending_pool(
    current_user: dict = Depends(require_roles(["DISPATCHER"])),
) -> dict:
    """返回待调度长审核的检修票工单池（仅 DISPATCHER 角色可访问）。"""
    return {
        "total": len(_PENDING_POOL),
        "reviewer_id": current_user.get("sub"),
        "items": _PENDING_POOL,
    }
