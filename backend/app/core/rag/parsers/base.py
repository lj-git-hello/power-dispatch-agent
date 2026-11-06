"""解析器基类与统一数据结构（通用 RAG 脚手架）。"""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from pydantic import BaseModel, Field


class ParsedDocument(BaseModel):
    """单个解析产物（一个文件可能产出多个，如分页、分块、分 Sheet）。"""

    # 文件或章节名
    title: str
    # 提取的纯文本
    content: str
    # 物理路径
    source_path: str
    # 后缀类型（不含点，小写）
    doc_type: str
    # 扩展字段：页码、块号、行列范围等
    metadata: dict = Field(default_factory=dict)


class BaseParser(ABC):
    """文档解析器抽象基类。

    主契约为惰性生成器 ``iter_parse``，子类按批次产出 ParsedDocument，
    避免一次性物化整篇 / 整表。
    """

    @abstractmethod
    def iter_parse(self, file_path: str) -> Iterator[ParsedDocument]:
        """流式解析：逐批 yield ParsedDocument。"""
        raise NotImplementedError

    def parse(self, file_path: str) -> list[ParsedDocument]:
        """物化便捷方法：返回完整列表。

        会将整篇 / 整表累积到内存，仅在确需全量时使用；
        大文件优先直接消费 ``iter_parse``。
        """
        return list(self.iter_parse(file_path))
