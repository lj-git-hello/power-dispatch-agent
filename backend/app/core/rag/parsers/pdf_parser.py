""".pdf 流式解析器：逐页提取非空文本并 yield，不累积整篇。"""

from collections.abc import Iterator
from pathlib import Path

from pypdf import PdfReader

from app.core.rag.parsers.base import BaseParser, ParsedDocument

META_PAGE_KEY = "page"
_PAGE_START_INDEX = 1


class PdfParser(BaseParser):
    """.pdf 流式解析器，每个非空页 yield 一个 ParsedDocument。"""

    def iter_parse(self, file_path: str) -> Iterator[ParsedDocument]:
        reader = PdfReader(file_path)
        name = Path(file_path).name

        for index, page in enumerate(reader.pages):
            page_text = (page.extract_text() or "").strip()
            if not page_text:
                continue
            yield ParsedDocument(
                title=f"{name}#page{index + _PAGE_START_INDEX}",
                content=page_text,
                source_path=file_path,
                doc_type="pdf",
                metadata={META_PAGE_KEY: index + _PAGE_START_INDEX},
            )
