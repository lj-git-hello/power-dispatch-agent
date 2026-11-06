"""通用向量数据库中枢（通用 RAG 脚手架）。

负责切片批量入库（分批 + 幂等防重）、高级混合过滤向量检索与文档软删除。
对接 SQLAlchemy 异步会话与 ai_knowledge_base 表，全链路分批提交、内存可控。
"""

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.rag.chunking import DocumentChunk
from app.core.rag.embeddings import EMBEDDING_DIM, EmbeddingService
from app.models.ai_schema import AIKnowledgeBase

# 入库默认批大小
DEFAULT_BATCH_SIZE = 50
DEFAULT_DOC_VERSION = "v1.0"

# 检索默认参数
DEFAULT_TOP_K = 3
DEFAULT_MIN_SIMILARITY = 0.5

# 余弦距离 -> 相似度换算
_SIMILARITY_FROM_DISTANCE = "1 - (embedding <=> CAST(:vec AS vector))"


def _vector_literal(vector: Sequence[float]) -> str:
    """把向量渲染为 pgvector 字面值字符串（CAST(:str AS vector)）。"""
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


class VectorStoreService:
    """向量存储与检索中枢。"""

    def __init__(self) -> None:
        self._embeddings = EmbeddingService()

    # ------------------------------------------------------------------
    # 入库
    # ------------------------------------------------------------------
    async def _flush_batch(
        self,
        batch: Sequence[DocumentChunk],
        doc_version: str,
    ) -> int:
        """处理一批切片：幂等过滤 → 向量化 → 写入提交。返回新插入数。"""
        doc_codes = list({chunk.doc_code for chunk in batch})

        async with AsyncSessionLocal() as session:
            # 一次查询本批涉及 doc_code 的全部已存在切片内容
            existing_rows = await session.execute(
                text(
                    "SELECT doc_code, content FROM ai_knowledge_base "
                    "WHERE doc_code = ANY(:codes)"
                ),
                {"codes": doc_codes},
            )
            existing_contents = {
                (doc_code, (content or "").strip())
                for doc_code, content in existing_rows
            }

            new_chunks = [
                chunk
                for chunk in batch
                if (chunk.doc_code, chunk.content.strip())
                not in existing_contents
            ]
            if not new_chunks:
                return 0

            vectors = await self._embeddings.get_embeddings(
                [chunk.content for chunk in new_chunks]
            )

            records = [
                AIKnowledgeBase(
                    doc_code=chunk.doc_code,
                    biz_tag=chunk.biz_tag,
                    section_title=chunk.section_title,
                    content=chunk.content,
                    embedding=vector,
                    doc_version=doc_version,
                )
                for chunk, vector in zip(new_chunks, vectors)
            ]
            session.add_all(records)
            await session.commit()
            return len(records)

    async def batch_upsert_chunks(
        self,
        chunks: Iterable[DocumentChunk],
        doc_version: str = DEFAULT_DOC_VERSION,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """分批消费切片流并入库，返回实际新插入记录总数（幂等防重）。"""
        if batch_size <= 0:
            raise ValueError("batch_size 必须为正整数。")

        inserted = 0
        buffer: list[DocumentChunk] = []
        for chunk in chunks:
            buffer.append(chunk)
            if len(buffer) >= batch_size:
                inserted += await self._flush_batch(buffer, doc_version)
                buffer = []

        if buffer:
            inserted += await self._flush_batch(buffer, doc_version)
        return inserted

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    async def search_advanced(
        self,
        query: str,
        biz_tag: str | None = None,
        doc_code: str | None = None,
        top_k: int = DEFAULT_TOP_K,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
    ) -> list[dict[str, Any]]:
        """高级向量检索：元数据预过滤 + HNSW 余弦距离 + 相似度阈值。"""
        query_vectors = await self._embeddings.get_embeddings([query])
        vec_str = _vector_literal(query_vectors[0])

        where_clauses = ["is_active = TRUE"]
        params: dict[str, Any] = {
            "vec": vec_str,
            "top_k": top_k,
            "min_sim": min_similarity,
        }
        if biz_tag is not None:
            where_clauses.append("biz_tag = :biz_tag")
            params["biz_tag"] = biz_tag
        if doc_code is not None:
            where_clauses.append("doc_code = :doc_code")
            params["doc_code"] = doc_code
        where_clauses.append(
            f"({_SIMILARITY_FROM_DISTANCE}) >= :min_sim"
        )

        sql = text(
            "SELECT doc_code, biz_tag, section_title, content, "
            f"{_SIMILARITY_FROM_DISTANCE} AS similarity "
            "FROM ai_knowledge_base "
            f"WHERE {' AND '.join(where_clauses)} "
            "ORDER BY embedding <=> CAST(:vec AS vector) "
            "LIMIT :top_k"
        )

        async with AsyncSessionLocal() as session:
            rows = await session.execute(sql, params)
            return [
                {
                    "doc_code": row.doc_code,
                    "biz_tag": row.biz_tag,
                    "section_title": row.section_title,
                    "content": row.content,
                    "similarity": float(row.similarity),
                }
                for row in rows
            ]

    # ------------------------------------------------------------------
    # 软删除
    # ------------------------------------------------------------------
    async def soft_delete_document(self, doc_code: str) -> int:
        """按 doc_code 软删除（is_active=FALSE），返回影响行数。"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(
                    "UPDATE ai_knowledge_base SET is_active = FALSE "
                    "WHERE doc_code = :doc_code AND is_active = TRUE"
                ),
                {"doc_code": doc_code},
            )
            await session.commit()
            return result.rowcount
