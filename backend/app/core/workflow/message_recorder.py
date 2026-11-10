"""通用 A2UI 卡片 / 消息快照持久化服务。"""

from typing import Any

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.ai_schema import AIChatMessage

# 卡片消息类型
KIND_CARD = "card"
KIND_TEXT = "text"


class MessageRecorder:
    """无状态消息记录器（静态方法）。"""

    @staticmethod
    async def record_card(
        thread_id: str,
        role: str,
        card_type: str,
        card_payload: dict[str, Any],
        retry_payload: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> AIChatMessage:
        """向 ai_chat_messages 写入结构化卡片与自包含重试载荷并提交。"""
        message = AIChatMessage(
            thread_id=thread_id,
            role=role,
            kind=KIND_CARD,
            content=content,
            card_type=card_type,
            card_payload=card_payload,
            retry_payload=retry_payload,
        )
        async with AsyncSessionLocal() as session:
            session.add(message)
            await session.commit()
        return message

    @staticmethod
    async def record_text(
        thread_id: str,
        role: str,
        content: str,
    ) -> AIChatMessage:
        """写入普通文本消息并提交。"""
        message = AIChatMessage(
            thread_id=thread_id,
            role=role,
            kind=KIND_TEXT,
            content=content,
        )
        async with AsyncSessionLocal() as session:
            session.add(message)
            await session.commit()
        return message

    @staticmethod
    async def list_by_thread(thread_id: str) -> list[dict[str, Any]]:
        """按 thread_id 读取消息 / 卡片快照，按 created_at 升序；无记录返回 []。

        JSONB 列由驱动还原为 dict；时间转 ISO 字符串，保证可 JSON 序列化。
        """
        sql = text(
            "SELECT id, thread_id, role, kind, content, card_type, "
            "card_payload, retry_payload, created_at "
            "FROM ai_chat_messages "
            "WHERE thread_id = :thread_id "
            "ORDER BY created_at ASC"
        )
        async with AsyncSessionLocal() as session:
            rows = await session.execute(sql, {"thread_id": thread_id})

        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row._mapping)
            created_at = item.get("created_at")
            if created_at is not None:
                item["created_at"] = created_at.isoformat()
            items.append(item)
        return items