"""通用向量接口（通用 RAG 脚手架）。

封装 Embedding 模型调用，提供确定性伪向量降级：
网络异常 / 超时 / 未配置 Key 时，基于内容 MD5 生成 L2 归一化伪向量，
保证无网环境与本地单测下检索链路 100% 畅通。
"""

import hashlib
import math
import os
import struct
from collections.abc import Sequence

import openai

# 输出向量维度，与 ai_knowledge_base.embedding Vector(1536) 绑定
EMBEDDING_DIM = 1536
# 单次请求最大文本数，控制请求体大小
EMBEDDING_BATCH_SIZE = 100
# 伪向量：每维用 4 字节哈希流构造（int32 -> 有符号分量）
PSEUDO_BYTES_PER_DIM = 4

# 环境变量键名
ENV_API_KEY = "OPENAI_API_KEY"
ENV_BASE_URL = "OPENAI_BASE_URL"
ENV_MODEL_NAME = "OPENAI_MODEL_NAME"
DEFAULT_MODEL_NAME = "text-embedding-3-small"


class EmbeddingService:
    """Embedding 生成服务：真实模型优先，确定性伪向量兜底。"""

    def __init__(self) -> None:
        self.api_key = os.getenv(ENV_API_KEY, "").strip()
        self.base_url = os.getenv(ENV_BASE_URL) or None
        self.model_name = (
            os.getenv(ENV_MODEL_NAME) or DEFAULT_MODEL_NAME
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
        """基于内容 MD5 的哈希链生成 1536 维 L2 归一化伪向量。

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
            # 理论上不可达（1536 维全 0 概率为 0），防御性兜底
            values[0] = 1.0
            norm = 1.0
        return [value / norm for value in values]

    # ------------------------------------------------------------------
    # 主路径
    # ------------------------------------------------------------------
    async def _embed_batch_real(
        self, batch: Sequence[str]
    ) -> list[list[float]]:
        response = await self._client.embeddings.create(
            model=self.model_name, input=list(batch)
        )
        # API 返回按 index 排序；显式按 index 排序更稳妥
        return [
            item.embedding for item in sorted(response.data, key=lambda d: d.index)
        ]

    async def get_embeddings(
        self, texts: Sequence[str]
    ) -> list[list[float]]:
        """批量生成 1536 维向量，分批请求；任一子批失败则该批降级。"""
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
            ):
                results.extend(self._pseudo_embedding(text) for text in batch)
        return results
