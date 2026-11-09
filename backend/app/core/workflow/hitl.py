"""通用人机协同（HITL）并发控制器。

集中收口三类跨业务操作：
- resume_with_cas：CAS 乐观锁抢占 + Command(resume) 唤醒工作流
- get_pending_tasks：按角色查询待办
- finalize_status：流程结束后回写终态 / 签名

垂直业务 Router 只做编排，不写任何底层 SQL。
"""

from typing import Any

from fastapi import HTTPException, status
from langgraph.types import Command
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.workflow.graph_registry import DEFAULT_GRAPH_NAME, GraphRegistry

# 通用状态常量（禁止魔法值）
STATUS_RUNNING = "RUNNING"
STATUS_WAITING_HUMAN = "WAITING_HUMAN"


class HITLController:
    """无状态 HITL 并发控制器（全部静态方法）。"""

    @staticmethod
    async def resume_with_cas(
        thread_id: str,
        lock_version: int,
        resume_payload: dict[str, Any],
        operator_id: str,
        audit_opinion: str | None = None,
        graph_name: str = DEFAULT_GRAPH_NAME,
    ) -> None:
        """CAS 抢占成功后，用 Command(resume) 唤醒对应工作流图。

        抢占失败（已被处理 / 版本失效）抛 409。
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    "UPDATE ai_thread_mappings "
                    "SET status = :running, "
                    "lock_version = lock_version + 1, "
                    "operator_id = :uid, "
                    "audit_opinion = :opinion "
                    "WHERE thread_id = :tid "
                    "AND lock_version = :ver "
                    "AND status = :waiting"
                ),
                {
                    "running": STATUS_RUNNING,
                    "uid": operator_id,
                    "opinion": audit_opinion,
                    "tid": thread_id,
                    "ver": lock_version,
                    "waiting": STATUS_WAITING_HUMAN,
                },
            )
            if result.rowcount == 0:
                await session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="任务已被其他操作人处理或版本已失效",
                )
            await session.commit()

        # 依赖反转：从注册中心取当前业务图，底座不感知具体业务
        graph = GraphRegistry.get_graph(graph_name)
        await graph.ainvoke(
            Command(resume=resume_payload),
            config={"configurable": {"thread_id": thread_id}},
        )

    @staticmethod
    async def get_pending_tasks(assigned_role: str) -> list[dict[str, Any]]:
        """查询指定角色的待办记录（WAITING_HUMAN）。"""
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                text(
                    "SELECT thread_id, session_id, creator_id, creator_dept, "
                    "status, assigned_role, lock_version, audit_opinion, "
                    "created_at "
                    "FROM ai_thread_mappings "
                    "WHERE status = :status AND assigned_role = :role "
                    "ORDER BY created_at"
                ),
                {
                    "status": STATUS_WAITING_HUMAN,
                    "role": assigned_role,
                },
            )
            items = [dict(row._mapping) for row in rows]

        for item in items:
            if item.get("created_at") is not None:
                item["created_at"] = item["created_at"].isoformat()
        return items

    @staticmethod
    async def finalize_status(
        thread_id: str,
        final_status: str,
        signature_hash: str | None = None,
    ) -> None:
        """流程结束后回写映射终态；可选落签名哈希。"""
        async with AsyncSessionLocal() as session:
            if signature_hash is not None:
                await session.execute(
                    text(
                        "UPDATE ai_thread_mappings "
                        "SET status = :status, signature_hash = :sig "
                        "WHERE thread_id = :tid"
                    ),
                    {
                        "status": final_status,
                        "sig": signature_hash,
                        "tid": thread_id,
                    },
                )
            else:
                await session.execute(
                    text(
                        "UPDATE ai_thread_mappings SET status = :status "
                        "WHERE thread_id = :tid"
                    ),
                    {"status": final_status, "tid": thread_id},
                )
            await session.commit()