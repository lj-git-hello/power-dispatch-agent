"""工业语义层级分块器（通用 RAG 脚手架）。

消费上游流式产出的 ParsedDocument，按层级标点递归切分并维护滑动重叠窗口，
逐片惰性 yield DocumentChunk。不在分块前物化全部 sections。
"""

import hashlib
from collections.abc import Iterator

from pydantic import BaseModel, model_validator

from app.core.rag.parsers.base import ParsedDocument

# 递归切分的分隔符层级：优先在大语义边界（段落/行）断开，
# 逐级退化到中文 / 西文句读，最后才硬切。
SEMANTIC_SEPARATORS: list[str] = [
    "\n\n",
    "\n",
    "；",
    "。",
    "！",
    "？",
    ";",
    ". ",
]

DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50


class DocumentChunk(BaseModel):
    """语义切片：带文档编码、业务标签、章节标识与内容指纹。"""

    # 规程编码，如 DL-408-2021
    doc_code: str
    # 业务标签，如 220kV
    biz_tag: str
    # 章节或页码标识
    section_title: str
    # 切片正文
    content: str
    # 在本文档中的切片顺序编号
    chunk_index: int
    # MD5 内容指纹，自动填充
    content_hash: str = ""

    @model_validator(mode="after")
    def _fill_content_hash(self) -> "DocumentChunk":
        # 未显式提供指纹时，按规范自动计算
        if not self.content_hash:
            self.content_hash = hashlib.md5(
                f"{self.doc_code}:{self.content.strip()}".encode()
            ).hexdigest()
        return self


class RecursiveSemanticChunker:
    """递归语义分块器：层级标点切分 + 滑动重叠。"""

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须为正整数。")
        if not 0 <= chunk_overlap < chunk_size:
            raise ValueError(
                "chunk_overlap 必须满足 0 <= overlap < chunk_size。"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ------------------------------------------------------------------
    # 基础切分
    # ------------------------------------------------------------------
    @staticmethod
    def _split_keep_separator(text: str, separator: str) -> list[str]:
        """切分并把分隔符附在非末尾块尾部，保留语义标点。"""
        raw_parts = text.split(separator)
        pieces: list[str] = []
        last_index = len(raw_parts) - 1
        for index, part in enumerate(raw_parts):
            piece = part if index == last_index else part + separator
            if piece:
                pieces.append(piece)
        return pieces

    def _hard_split(self, text: str) -> list[str]:
        """无可用分隔符时按固定长度硬切，保证不超长。"""
        return [
            text[i : i + self.chunk_size]
            for i in range(0, len(text), self.chunk_size)
        ]

    def _recursive_split(
        self, text: str, separators: list[str]
    ) -> list[str]:
        """在分隔符层级上递归切分，返回长度不超过 chunk_size 的片段。"""
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        # 找到文本中实际存在的最高优先级分隔符
        separator_index = next(
            (
                index
                for index, separator in enumerate(separators)
                if separator and separator in text
            ),
            None,
        )
        if separator_index is None:
            return self._hard_split(text)

        separator = separators[separator_index]
        pieces: list[str] = []
        for part in self._split_keep_separator(text, separator):
            if len(part) <= self.chunk_size:
                pieces.append(part)
            else:
                # 切分后的 part 已不含当前分隔符，递归到更低层级
                pieces.extend(
                    self._recursive_split(
                        part, separators[separator_index + 1 :]
                    )
                )
        return pieces

    def _pack(self, pieces: list[str]) -> list[str]:
        """greedy 合并片段至接近 chunk_size，并维护尾部重叠。"""
        docs: list[str] = []
        buffer_pieces: list[str] = []
        total = 0

        for piece in pieces:
            if buffer_pieces and total + len(piece) > self.chunk_size:
                document = "".join(buffer_pieces)
                docs.append(document)

                # 从已产出文档尾部取重叠种子
                seed = (
                    document[-self.chunk_overlap :]
                    if self.chunk_overlap > 0
                    else ""
                )
                if seed and len(seed) + len(piece) <= self.chunk_size:
                    buffer_pieces = [seed]
                    total = len(seed)
                else:
                    # 种子与该片段无法共存：对此边界放弃重叠，避免产生纯重复小块
                    buffer_pieces = []
                    total = 0

            buffer_pieces.append(piece)
            total += len(piece)

        if buffer_pieces:
            docs.append("".join(buffer_pieces))

        return [document for document in docs if document.strip()]

    # ------------------------------------------------------------------
    # 对外主契约（惰性生成器）
    # ------------------------------------------------------------------
    def iter_split_sections(
        self,
        sections: Iterator[ParsedDocument],
        doc_code: str,
        biz_tag: str,
    ) -> Iterator[DocumentChunk]:
        """逐 section 流式切片，chunk_index 跨 section 连续递增。

        重叠仅在同一 section 的相邻切片之间保持，不跨 section（章节/页）重叠，
        避免跨语义单元污染。
        """
        chunk_index = 0
        for section in sections:
            if not section.content or not section.content.strip():
                continue
            pieces = self._recursive_split(
                section.content, SEMANTIC_SEPARATORS
            )
            for text in self._pack(pieces):
                yield DocumentChunk(
                    doc_code=doc_code,
                    biz_tag=biz_tag,
                    section_title=section.title,
                    content=text,
                    chunk_index=chunk_index,
                )
                chunk_index += 1

    def split_sections(
        self,
        sections: Iterator[ParsedDocument],
        doc_code: str,
        biz_tag: str,
    ) -> list[DocumentChunk]:
        """物化便捷方法（会累积整篇，仅在确需全量时使用）。"""
        return list(
            self.iter_split_sections(sections, doc_code, biz_tag)
        )
