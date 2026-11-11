"""通用向量接口（通用 RAG 脚手架）。

封装 Embedding 模型调用，提供确定性伪向量降级：
网络异常 / 超时 / 未配置 Key 时，基于内容 MD5 生成 L2 归一化伪向量，
保证无网环境与本地单测下检索链路 100% 畅通。

向量模型配置与聊天模型解耦（独立 EMBEDDING_* 变量），不再复用
OPENAI_MODEL_NAME（那是聊天模型，无法用于 embeddings 接口）。
"""

import hashlib
import logging
import math
import os
import struct
from collections.abc import Sequence

import openai

logger = logging.getLogger(__name__)

# 单次请求最大文本数。
# 【关键防御】实测当前编码套餐 embeddings 入口存在批量行为异常：当一次请求
# 文本数 >= 16 时，返回的向量会落入与小批量（≤8）不同的表示空间（二者
# 余弦≈0、完全正交）。入库若按大批量发送，而查询只发单条，两边向量空间
# 不一致会导致检索全部失效。故将批大小锁定在已验证安全的 8，
# 不要在未重新验证的情况下调大。
EMBEDDING_BATCH_SIZE = 8
# 伪向量：每维用 4 字节哈希流构造（int32 -> 有符号分量）
PSEUDO_BYTES_PER_DIM = 4

# 向量模型独立环境变量键名（EMBEDDING_*）
ENV_EMBEDDING_API_KEY = "EMBEDDING_API_KEY"
ENV_EMBEDDING_BASE_URL = "EMBEDDING_BASE_URL"
ENV_EMBEDDING_MODEL_NAME = "EMBEDDING_MODEL_NAME"
ENV_EMBEDDING_DIM = "EMBEDDING_DIM"

# 未显式配置时的回退：复用聊天侧入口 / 凭证
ENV_FALLBACK_API_KEY = "OPENAI_API_KEY"
ENV_FALLBACK_BASE_URL = "OPENAI_BASE_URL"

# 默认向量模型（火山方舟 doubao-embedding-vision）。
# 该模型原生 2048 维，但支持 Matryoshka 套娃降维；此处显式请求 1024 维——
# 既满足 pgvector ANN 索引 ≤2000 维的硬限制，又保持完整可用的向量表示。
DEFAULT_MODEL_NAME = "doubao-embedding-vision"
DEFAULT_EMBEDDING_DIM = 1024


def _resolve_embedding_dim() -> int:
    """读取向量维度，非法值回退默认。"""
    try:
        dim = int(os.getenv(ENV_EMBEDDING_DIM, str(DEFAULT_EMBEDDING_DIM)))
        return dim if dim > 0 else DEFAULT_EMBEDDING_DIM
    except ValueError:
        return DEFAULT_EMBEDDING_DIM


# 输出向量维度，与 ai_knowledge_base.embedding Vector 维度绑定
EMBEDDING_DIM = _resolve_embedding_dim()


class EmbeddingService:
    """Embedding 生成服务：真实模型优先，确定性伪向量兜底。"""

    def __init__(self) -> None:
        # 向量专用变量优先，缺省回退聊天侧配置（base_url / key 通常相同）
        self.api_key = (
            os.getenv(ENV_EMBEDDING_API_KEY)
            or os.getenv(ENV_FALLBACK_API_KEY, "")
        ).strip()
        self.base_url = (
            os.getenv(ENV_EMBEDDING_BASE_URL)
            or os.getenv(ENV_FALLBACK_BASE_URL)
            or None
        )
        self.model_name = (
            os.getenv(ENV_EMBEDDING_MODEL_NAME) or DEFAULT_MODEL_NAME
        )
        # key 缺失时仍构造客户端（不主动调用即不报错），统一降级路径
        self._client = openai.AsyncOpenAI(
            api_key=self.api_key or "missing",
            base_url=self.base_url,
        )

    # ------------------------------------------------------------------
    # 降级：确定性伪向量
    # ------------------------------------------------------------------
    @staticmethod
    def _pseudo_embedding(text: str) -> list[float]:
        """基于内容 MD5 的哈希链生成 EMBEDDING_DIM 维 L2 归一化伪向量。

        - 确定性：相同文本 → 相同向量；
        - 内容决定距离：不同文本经不同 MD5 链 → 不同向量；
        - L2 归一化：与余弦距离度量兼容。
        """
        needed_bytes = EMBEDDING_DIM * PSEUDO_BYTES_PER_DIM
        digest = hashlib.md5(text.encode("utf-8")).digest()

        byte_stream = bytearray()
        while len(byte_stream) < needed_bytes:
            byte_stream.extend(digest)
            # 哈希链：前一 digest 派生后一 digest
            digest = hashlib.md5(digest).digest()

        raw_bytes = bytes(byte_stream[:needed_bytes])
        values = [
            float(struct.unpack_from("<i", raw_bytes, offset)[0])
            for offset in range(0, needed_bytes, PSEUDO_BYTES_PER_DIM)
        ]
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            # 理论上不可达，防御性兜底
            values[0] = 1.0
            norm = 1.0
        return [value / norm for value in values]

    # ------------------------------------------------------------------
    # 主路径
    # ------------------------------------------------------------------
    async def _embed_batch_real(
        self, batch: Sequence[str]
    ) -> list[list[float]]:
        # 显式传 dimensions 触发 Matryoshka 降维到 1024
        response = await self._client.embeddings.create(
            model=self.model_name,
            input=list(batch),
            dimensions=EMBEDDING_DIM,
        )
        # API 返回按 index 排序；显式按 index 排序更稳妥
        return [
            item.embedding for item in sorted(response.data, key=lambda d: d.index)
        ]

    async def get_embeddings(
        self, texts: Sequence[str]
    ) -> list[list[float]]:
        """批量生成向量，分批请求；任一子批失败则该批降级。"""
        if not texts:
            return []

        results: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            try:
                if not self.api_key:
                    raise openai.APIConnectionError(request=None)
                results.extend(await self._embed_batch_real(batch))
            except (
                openai.APITimeoutError,
                openai.APIConnectionError,
                openai.RateLimitError,
                openai.APIError,
                # 供应商返回空 data 时，openai SDK 抛的是裸 ValueError
                # （openai/lib/_parsing/_embeddings.py: "No embedding data received"），
                # 不属于 APIError 体系，必须显式纳入降级范围。
                ValueError,
            ):
                logger.warning(
                    "Embedding 批次失败，降级为确定性伪向量（批起始位置=%d）",
                    start,
                    exc_info=True,
                )
                results.extend(self._pseudo_embedding(text) for text in batch)
            except Exception:  # noqa: BLE001 —— 兜底：任何未预期异常都不得中断入库链路
                logger.exception(
                    "Embedding 批次异常，降级为确定性伪向量（批起始位置=%d）",
                    start,
                )
                results.extend(self._pseudo_embedding(text) for text in batch)
        return results
