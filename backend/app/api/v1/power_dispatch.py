"""电力垂直业务路由 —— 检修申请 / 待办池 / 核签（HITL + CAS）。

业务流程经 DispatchState 状态机执行，持久化映射表（ai_thread_mappings）
记录状态机指针与角色/版本，卡片载荷写入 ai_chat_messages。
通用底盘（鉴权 / 生命周期）不感知电力业务概念。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.security import get_current_user, require_roles
from app.core.database import AsyncSessionLocal
from app.models.ai_schema import AIChatMessage, AIThreadMapping
from langgraph.types import Command

router = APIRouter(
    prefix="/power/dispatch", tags=["Power-Dispatch-Business"]
)


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
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
# 常量（状态/角色，禁止魔法值）
# ---------------------------------------------------------------------------
STATUS_WAITING_HUMAN = "WAITING_HUMAN"
STATUS_RUNNING = "RUNNING"
STATUS_PERMITTED = "PERMITTED"
STATUS_REJECTED = "REJECTED"
ROLE_DISPATCHER = "DISPATCHER"
ROLE_APPLICANT = "APPLICANT"

KIND_CARD = "card"
KIND_TEXT = "text"


def _graph():
    """获取已在 lifespan 挂载、绑定 Postgres checkpointer 的状态机。"""
    from main import graph_app

    if graph_app is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="状态机尚未就绪，请稍后重试。",
        )
    return graph_app


# ---------------------------------------------------------------------------
# POST /apply
# ---------------------------------------------------------------------------
@router.post("/apply")
async def apply_dispatch(
    req: ApplyRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """提报检修申请：建映射 → 驱动状态机至挂起 → 记录初审卡片。"""
    user_id = current_user["sub"]
    # 单会话多工单：基于 session_id 派生独立 thread_id
    thread_id = f"{req.session_id}_{uuid.uuid4().hex[:12]}"

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

    # 驱动状态机执行至 interrupt 挂起
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "thread_id": thread_id,
        "session_id": req.session_id,
        "user_id": user_id,
        "substation": req.substation,
        "voltage_level": req.voltage_level,
        "operation_task": req.operation_task,
        "safety_measures": req.safety_measures,
        "violations": [],
        "biz_order_id": None,
        "audit_decision": None,
        "permit_info": None,
    }
    await _graph().ainvoke(initial_state, config=config)

    # 读取挂起快照，提取初审结果 / 等待上下文
    snapshot = await _graph().aget_state(config)
    interrupted_payload = (
        snapshot.tasks[0].interrupts[0].value if snapshot.interrupts else {}
    )
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

    # 初审卡片写 ai_chat_messages
    async with AsyncSessionLocal() as session:
        session.add(
            AIChatMessage(
                thread_id=thread_id,
                role="assistant",
                kind=KIND_CARD,
                content="检修申请已提交，等待调度长核签。",
                card_type="dispatcher_audit",
                card_payload=card_payload,
            )
        )
        await session.commit()

    return {
        "thread_id": thread_id,
        "status": STATUS_WAITING_HUMAN,
        "interrupted": bool(interrupted_payload),
        "card": card_payload,
    }


# ---------------------------------------------------------------------------
# GET /tasks
# ---------------------------------------------------------------------------
@router.get("/tasks")
async def list_tasks(
    current_user: dict = Depends(require_roles([ROLE_DISPATCHER])),
) -> dict:
    """调度长待办池：WAITING_HUMAN 且 assigned_role=DISPATCHER。"""
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            text(
                "SELECT thread_id, session_id, creator_id, creator_dept, "
                "status, assigned_role, lock_version, created_at "
                "FROM ai_thread_mappings "
                "WHERE status = :status AND assigned_role = :role "
                "ORDER BY created_at"
            ),
            {"status": STATUS_WAITING_HUMAN, "role": ROLE_DISPATCHER},
        )
        items = [dict(row._mapping) for row in rows]

    for item in items:
        if item.get("created_at") is not None:
            item["created_at"] = item["created_at"].isoformat()

    return {
        "total": len(items),
        "reviewer_id": current_user["sub"],
        "items": items,
    }


# ---------------------------------------------------------------------------
# POST /audit
# ---------------------------------------------------------------------------
@router.post("/audit")
async def audit_dispatch(
    req: AuditRequest,
    current_user: dict = Depends(require_roles([ROLE_DISPATCHER])),
) -> dict:
    """调度长核签：CAS 抢占状态行 → Command(resume) 唤醒 → 终态与凭证落库。"""
    reviewer_id = current_user["sub"]

    # ---- CAS 乐观锁防抢审 ----
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "UPDATE ai_thread_mappings "
                "SET status = :running, lock_version = lock_version + 1, "
                "operator_id = :uid "
                "WHERE thread_id = :tid AND lock_version = :ver "
                "AND status = :waiting"
            ),
            {
                "running": STATUS_RUNNING,
                "uid": reviewer_id,
                "tid": req.thread_id,
                "ver": req.lock_version,
                "waiting": STATUS_WAITING_HUMAN,
            },
        )
        if result.rowcount == 0:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该工单已被其他调度长处理或版本已变更，操作被拦截。",
            )
        await session.commit()
        new_version = req.lock_version + 1

    # ---- Command(resume) 唤醒状态机跑至完成 ----
    config = {"configurable": {"thread_id": req.thread_id}}
    resume_command = Command(
        resume={
            "is_permitted": req.is_permitted,
            "opinion": req.opinion,
            "reviewer_id": reviewer_id,
        }
    )
    await _graph().ainvoke(resume_command, config=config)

    final_snapshot = await _graph().aget_state(config)
    final_state = dict(final_snapshot.values)

    permit_info = final_state.get("permit_info")
    final_status = (
        STATUS_PERMITTED if req.is_permitted else STATUS_REJECTED
    )

    # 许可令/驳回卡片写 ai_chat_messages
    async with AsyncSessionLocal() as session:
        session.add(
            AIChatMessage(
                thread_id=req.thread_id,
                role="assistant",
                kind=KIND_CARD,
                content=(
                    "调度许可令已签发。"
                    if req.is_permitted
                    else "调度长已驳回本次检修申请。"
                ),
                card_type="permit_result",
                card_payload={
                    "thread_id": req.thread_id,
                    "status": final_status,
                    "biz_order_id": final_state.get("biz_order_id"),
                    "permit_info": permit_info,
                    "opinion": req.opinion,
                },
            )
        )
        # 终态回写映射表
        await session.execute(
            text(
                "UPDATE ai_thread_mappings SET status = :status "
                "WHERE thread_id = :tid"
            ),
            {"status": final_status, "tid": req.thread_id},
        )
        await session.commit()

    return {
        "thread_id": req.thread_id,
        "status": final_status,
        "lock_version": new_version,
        "permit_info": permit_info,
    }
