"""AI 中台企业级数据模型定义（SQLAlchemy 2.0 异步规范）。

“3+N”架构：
- AIThreadMapping：核心调度中枢（线程/会话映射、状态机指针、CAS 乐观锁）
- AIChatMessage：交互载荷与卡片快照（与中枢表纯逻辑关联，不建物理外键）
- AIExecutionTrace：运行审计与可观测 Trace（Token、成本、时延、工具调用）
- AIKnowledgeBase：N 张扩展表之一，安规向量知识库（pgvector + HNSW）
"""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全模型声明式基类。"""

    pass


class AIThreadMapping(Base):
    """核心调度中枢表：底层引擎线程与前端会话 / 业务工单的映射。"""

    __tablename__ = "ai_thread_mappings"

    # 底层引擎线程ID
    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 前端UI会话ID
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 外部业务弱引用
    biz_order_id: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    # 幂等防护键
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    creator_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    creator_dept: Mapped[str | None] = mapped_column(String(64), nullable=True)
    creator_role: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_role: Mapped[str] = mapped_column(
        String(32),
        index=True,
        server_default=text("'APPLICANT'"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        index=True,
        server_default=text("'DRAFT'"),
        nullable=False,
    )
    # 状态机当前节点指针
    current_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # CAS 乐观锁版本号
    lock_version: Mapped[int] = mapped_column(
        Integer, server_default=text("1"), default=1, nullable=False
    )
    operator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audit_opinion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 调度长核签签名摘要
    signature_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("false"),
        default=False,
        index=True,
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AIChatMessage(Base):
    """交互载荷与卡片快照表。

    与 ai_thread_mappings 保持纯逻辑关联（thread_id），不建立物理外键，
    避免高并发会话清理时的外键校验与死锁。
    """

    __tablename__ = "ai_chat_messages"
    __table_args__ = (
        Index("idx_chat_thread_created", "thread_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16),
        server_default=text("'text'"),
        default="text",
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    card_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retry_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_sanitized: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIExecutionTrace(Base):
    """运行审计与可观测 Trace 表：节点级 Token、成本、时延与工具调用留痕。"""

    __tablename__ = "ai_execution_traces"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    thread_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), default=0, nullable=False
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), default=0, nullable=False
    )
    total_cost: Mapped[float] = mapped_column(
        Numeric(10, 4),
        server_default=text("0.0000"),
        default=0.0,
        nullable=False,
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIKnowledgeBase(Base):
    """安规向量知识库表：条款切片 + 1024 维 Embedding（HNSW 余弦检索）。

    维度说明：底层 doubao-embedding-vision 原生输出 1536 维，经 Matryoshka
    显式降维到 1024 维（迁移脚本 844a9489b970_resize_embedding_to_1024.py），
    以满足 pgvector ANN 索引 ≤2000 维的硬限制，同时降低存储与检索开销。
    """

    __tablename__ = "ai_knowledge_base"
    __table_args__ = (
        # 元数据预过滤优化
        Index("idx_knowledge_tag_active", "biz_tag", "is_active"),
        # HNSW 向量索引
        Index(
            "idx_knowledge_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    doc_code: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    biz_tag: Mapped[str] = mapped_column(String(32), nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    doc_version: Mapped[str] = mapped_column(
        String(32),
        server_default=text("'v1.0'"),
        default="v1.0",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "Base",
    "AIThreadMapping",
    "AIChatMessage",
    "AIExecutionTrace",
    "AIKnowledgeBase",
]