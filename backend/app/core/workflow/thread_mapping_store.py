"""通用线程映射中枢（建档 / 归档 / 幂等键）。

ai_thread_mappings 是通用层的"调度中枢表"，其写入逻辑必须收口在
core 层：业务插件只描述"建一条什么样的映射"，不直接触碰 ORM。
与 MessageRecorder 保持同一范式：通用层封装持久化，插件只做编排。
"""

from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.ai_schema import AIThreadMapping

# 通用初始状态（业务插件可覆盖为自身语义）
STATUS_DRAFT = "DRAFT"
# 通用活跃状态（无状态机的纯对话线程）
STATUS_ACTIVE = "ACTIVE"
# 通用兜底角色（无状态机的纯对话线程）
ROLE_SYSTEM = "SYSTEM"


class ThreadMappingStore:
    """无状态线程映射仓储（全部静态方法）。"""

    @staticmethod
    async def create_mapping(
        thread_id: str,
        session_id: str,
        creator_id: str,
        creator_role: str,
        assigned_role: str,
        creator_dept: str | None = None,
        status: str = STATUS_DRAFT,
        idempotency_key: str | None = None,
    ) -> AIThreadMapping:
        """建立线程映射（幂等）：已存在则原样返回，不重复插入。"""
        async with AsyncSessionLocal() as session:
            existing = await session.get(AIThreadMapping, thread_id)
            if existing is not None:
                return existing

            mapping = AIThreadMapping(
                thread_id=thread_id,
                session_id=session_id,
                creator_id=creator_id,
                creator_role=creator_role,
                creator_dept=creator_dept,
                assigned_role=assigned_role,
                status=status,
                lock_version=1,
                idempotency_key=idempotency_key,
            )
            session.add(mapping)
            try:
                await session.commit()
            except IntegrityError:
                # 并发重复建档：回滚后取已存在记录
                await session.rollback()
                existing = await session.get(AIThreadMapping, thread_id)
                if existing is not None:
                    return existing
                raise
            return mapping

    @staticmethod
    async def archive(thread_id: str) -> bool:
        """归档线程映射（软删除）；返回是否命中记录。"""
        async with AsyncSessionLocal() as session:
            mapping = await session.get(AIThreadMapping, thread_id)
            if mapping is None:
                return False
            mapping.is_archived = True
            await session.commit()
            return True

    @staticmethod
    async def get(thread_id: str) -> dict[str, Any] | None:
        """读取线程映射快照；不存在返回 None。"""
        async with AsyncSessionLocal() as session:
            mapping = await session.get(AIThreadMapping, thread_id)
            if mapping is None:
                return None
            return {
                "thread_id": mapping.thread_id,
                "session_id": mapping.session_id,
                "creator_id": mapping.creator_id,
                "creator_role": mapping.creator_role,
                "assigned_role": mapping.assigned_role,
                "status": mapping.status,
                "lock_version": mapping.lock_version,
                "current_node": mapping.current_node,
                "is_archived": mapping.is_archived,
            }


__all__ = [
    "ROLE_SYSTEM",
    "STATUS_ACTIVE",
    "STATUS_DRAFT",
    "ThreadMappingStore",
]
