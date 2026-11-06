"""通用 RAG 脚手架核心导出。

对外暴露语义分块、向量化与向量存储检索三类核心能力：

    from app.core.rag import (
        RecursiveSemanticChunker, EmbeddingService, VectorStoreService,
    )
"""

from app.core.rag.chunking import DocumentChunk, RecursiveSemanticChunker
from app.core.rag.embeddings import EmbeddingService
from app.core.rag.vector_service import VectorStoreService

__all__ = [
    "DocumentChunk",
    "RecursiveSemanticChunker",
    "EmbeddingService",
    "VectorStoreService",
]
