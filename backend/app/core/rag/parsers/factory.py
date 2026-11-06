"""文档解析器门面工厂：按文件后缀路由到具体解析器。"""

from collections.abc import Iterator
from pathlib import Path

from app.core.rag.parsers.base import BaseParser, ParsedDocument
from app.core.rag.parsers.docx_parser import DocxParser
from app.core.rag.parsers.excel_parser import ExcelParser
from app.core.rag.parsers.pdf_parser import PdfParser
from app.core.rag.parsers.text_parser import TextParser


class UnsupportedFileTypeError(Exception):
    """不支持的文件后缀时抛出。"""


# 后缀（不含点、小写）-> 解析器类的集中映射（禁止魔法值散落）
_PARSER_REGISTRY: dict[str, type[BaseParser]] = {
    "txt": TextParser,
    "md": TextParser,
    "docx": DocxParser,
    "pdf": PdfParser,
    "xlsx": ExcelParser,
    "csv": ExcelParser,
}


class DocumentParserFactory:
    """解析器门面：对外屏蔽具体解析器选择细节。"""

    @staticmethod
    def get_parser(file_path: str) -> BaseParser:
        """根据后缀返回对应解析器实例；未知后缀抛 UnsupportedFileTypeError。"""
        suffix = Path(file_path).suffix.lstrip(".").lower()
        parser_cls = _PARSER_REGISTRY.get(suffix)
        if parser_cls is None:
            raise UnsupportedFileTypeError(
                f"不支持的文件类型：.{suffix}（file_path={file_path}）"
            )
        return parser_cls()

    @staticmethod
    def iter_file(file_path: str) -> Iterator[ParsedDocument]:
        """流式便捷方法：惰性产出 ParsedDocument，推荐大文件使用。"""
        return DocumentParserFactory.get_parser(file_path).iter_parse(file_path)

    @staticmethod
    def parse_file(file_path: str) -> list[ParsedDocument]:
        """物化便捷方法：返回完整列表（会整篇入内存，小文件 / 确需全量时用）。"""
        return list(DocumentParserFactory.iter_file(file_path))
