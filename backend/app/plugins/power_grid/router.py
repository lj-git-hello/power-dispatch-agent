"""电网检修调度业务路由（垂直插件）。

仅做 HTTP 编排：鉴权、参数校验、驱动图、调用通用底座。
本文件不含任何 SQL（CAS / 待办 / 消息持久化 / 终态回写全部委托 core.workflow）。
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_current_user, require_roles
from app.core.workflow import (
    HITLController,
    MessageRecorder,
)
from app.models.ai_schema import AIThreadMapping
from app.core.database import AsyncSessionLocal

# 路由自身不带前缀：由 main 统一挂 /api/v1/power-dispatch
power_dispatch_router = APIRouter(tags=["Power-Dispatch"])

# 角色 / 状态
ROLE_DISPATCHER = "DISPATCHER"
ROLE_APPLICANT = "APPLICANT"
STATUS_WAITING_HUMAN = "WAITING_HUMAN"
STATUS_PERMITTED = "PERMITTED"
STATUS_REJECTED = "REJECTED"


class ApplyRequest(BaseModel):
    """检修提报请求。"""

    session_id: str
    substation: str
    voltage_level: str
    operation_task: str
    safety_measures: list[str]


class AuditRequest(BaseModel):
    """调度长核签请求。"""

    thread_id: str
    lock_version: int
    is_permitted: bool
    opinion: str = ""


# ---------------------------------------------------------------------------
# POST /apply
# ---------------------------------------------------------------------------
@power_dispatch_router.post("/apply")
async def apply_dispatch(
    req: ApplyRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """派生 thread → 建初始映射 → 驱动图至挂起 → 落初审卡片。"""
    user_id = current_user["sub"]
    thread_id = f"{req.session_id}_{uuid.uuid4().hex[:12]}"

    # 初始映射（此处仅做 ORM 插入，非手写 SQL；属提报建档动作）
    async with AsyncSessionLocal() as session:
        session.add(
            AIThreadMapping(
                thread_id=thread_id,
                session_id=req.session_id,
                creator_id=user_id,
                creator_role=ROLE_APPLICANT,
                creator_dept=current_user.get("dept"),
                assigned_role=ROLE_DISPATCHER,
                status=STATUS_WAITING_HUMAN,
                lock_version=1,
            )
        )
        await session.commit()

    # 取已注册的电网图（lifespan / 测试 bootstrap 时注册）
    from app.core.workflow import GraphRegistry

    graph = GraphRegistry.get_graph()

    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(
        {
            "thread_id": thread_id,
            "session_id": req.session_id,
            "user_id": user_id,
            "status": STATUS_WAITING_HUMAN,
            "error": None,
            "substation": req.substation,
            "voltage_level": req.voltage_level,
            "operation_task": req.operation_task,
            "safety_measures": req.safety_measures,
            "violations": [],
            "biz_order_id": None,
            "audit_decision": None,
            "permit_info": None,
        },
        config=config,
    )

    snapshot = await graph.aget_state(config)
    state_values = dict(snapshot.values)

    card_payload = {
        "card_type": "dispatcher_audit",
        "thread_id": thread_id,
        "biz_order_id": state_values.get("biz_order_id"),
        "substation": req.substation,
        "voltage_level": req.voltage_level,
        "operation_task": req.operation_task,
        "violations": state_values.get("violations", []),
        "lock_version": 1,
    }
    await MessageRecorder.record_card(
        thread_id=thread_id,
        role="assistant",
        card_type="dispatcher_audit",
        card_payload=card_payload,
        retry_payload={"thread_id": thread_id, "lock_version": 1},
        content="检修申请已提交，等待调度长核签。",
    )

    return {
        "thread_id": thread_id,
        "status": STATUS_WAITING_HUMAN,
        "interrupted": bool(snapshot.interrupts),
        "card": card_payload,
    }


# ---------------------------------------------------------------------------
# GET /tasks
# ---------------------------------------------------------------------------
@power_dispatch_router.get("/tasks")
async def list_tasks(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """待办任务审批池（Pending Task Pool）。

    角色由后端依据 JWT 判定，忽略任何前端传入的角色参数：
    - DISPATCHER：返回其名下 WAITING_HUMAN 待审工单；
    - APPLICANT（及其它非审批角色）：允许访问，安全返回空列表，不抛 403。
    """
    if current_user.get("role") == ROLE_DISPATCHER:
        items = await HITLController.get_pending_tasks(ROLE_DISPATCHER)
    else:
        items = []
    return {
        "total": len(items),
        "reviewer_id": current_user["sub"],
        "items": items,
    }


# ---------------------------------------------------------------------------
# GET /messages
# ---------------------------------------------------------------------------
@power_dispatch_router.get("/messages")
async def list_thread_messages(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """按 thread_id 读取消息 / 卡片快照（只读）；无记录返回空列表。"""
    items = await MessageRecorder.list_by_thread(thread_id)
    return {
        "thread_id": thread_id,
        "requester_id": current_user["sub"],
        "items": items,
    }


# ---------------------------------------------------------------------------
# POST /audit
# ---------------------------------------------------------------------------
@power_dispatch_router.post("/audit")
async def audit_dispatch(
    req: AuditRequest,
    current_user: dict = Depends(require_roles([ROLE_DISPATCHER])),
) -> dict:
    """CAS 抢占 + Command 唤醒 → 落终态凭证卡片 → 回写终态。"""
    reviewer_id = current_user["sub"]

    # 通用底座：CAS + 唤醒（失败由底座抛 409）
    await HITLController.resume_with_cas(
        thread_id=req.thread_id,
        lock_version=req.lock_version,
        resume_payload={
            "is_permitted": req.is_permitted,
            "opinion": req.opinion,
            "reviewer_id": reviewer_id,
        },
        operator_id=reviewer_id,
        audit_opinion=req.opinion or None,
    )

    # 读终态快照（图已完成）
    from app.core.workflow import GraphRegistry

    graph = GraphRegistry.get_graph()
    config = {"configurable": {"thread_id": req.thread_id}}
    final_snapshot = await graph.aget_state(config)
    final_state = dict(final_snapshot.values)

    permit_info = final_state.get("permit_info")
    final_status = (
        STATUS_PERMITTED if req.is_permitted else STATUS_REJECTED
    )
    signature_hash = (
        permit_info.get("ca_signature_hash") if permit_info else None
    )

    # 终态凭证卡片（委托 recorder）
    await MessageRecorder.record_card(
        thread_id=req.thread_id,
        role="assistant",
        card_type="permit_result",
        card_payload={
            "thread_id": req.thread_id,
            "status": final_status,
            "biz_order_id": final_state.get("biz_order_id"),
            "permit_info": permit_info,
            "opinion": req.opinion,
        },
        content=(
            "调度许可令已签发。"
            if req.is_permitted
            else "调度长已驳回本次检修申请。"
        ),
    )

    # 终态回写（委托 HITLController，Router 不写 UPDATE SQL）
    await HITLController.finalize_status(
        thread_id=req.thread_id,
        final_status=final_status,
        signature_hash=signature_hash,
    )

    return {
        "thread_id": req.thread_id,
        "status": final_status,
        "permit_info": permit_info,
    }