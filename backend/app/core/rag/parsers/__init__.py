"""多格式文档解析器（通用 RAG 脚手架）。

对外统一导出解析产物类型与门面工厂：
    docs = DocumentParserFactory.parse_file(file_path)
"""

from app.core.rag.parsers.base import BaseParser, ParsedDocument
from app.core.rag.parsers.factory import (
    DocumentParserFactory,
    UnsupportedFileTypeError,
)

# 模块级便捷函数
iter_file = DocumentParserFactory.iter_file
parse_file = DocumentParserFactory.parse_file

__all__ = [
    "BaseParser",
    "ParsedDocument",
    "DocumentParserFactory",
    "UnsupportedFileTypeError",
    "iter_file",
    "parse_file",
]
