"""纯文本 / Markdown 解析器：逐行惰性读取，按字符阈值分批产出。"""

from collections.abc import Iterator
from pathlib import Path

from app.core.rag.parsers.base import BaseParser, ParsedDocument

# 仅读取固定大小前缀用于判定编码（常量内存，不读整篇）
_ENCODING_SNIFF_BYTES = 4096
CANDIDATE_ENCODINGS = ("utf-8", "gbk")
# 单个产出块的最大字符数（达到即在行边界切分）
TEXT_MAX_CHUNK_CHARS = 2000


def _sniff_encoding(file_path: str) -> str:
    """读取小前缀判定编码；均无法严格解码时回退 utf-8（读取时容错）。"""
    with open(file_path, "rb") as handle:
        prefix = handle.read(_ENCODING_SNIFF_BYTES)
    for encoding in CANDIDATE_ENCODINGS:
        try:
            prefix.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return CANDIDATE_ENCODINGS[0]


class TextParser(BaseParser):
    """.txt / .md 流式解析器：逐行读入，按字符阈值分批 yield。"""

    def iter_parse(self, file_path: str) -> Iterator[ParsedDocument]:
        encoding = _sniff_encoding(file_path)
        name = Path(file_path).name
        doc_type = Path(file_path).suffix.lstrip(".").lower()

        buffer: list[str] = []
        buffer_chars = 0
        part = 0
        start_line = 1
        line_no = 0

        def _flush() -> ParsedDocument:
            nonlocal part, buffer, buffer_chars, start_line
            part += 1
            content = "".join(buffer)
            document = ParsedDocument(
                title=f"{name}#part{part}",
                content=content,
                source_path=file_path,
                doc_type=doc_type,
                metadata={
                    "part": part,
                    "start_line": start_line,
                    "end_line": line_no,
                },
            )
            buffer = []
            buffer_chars = 0
            start_line = line_no + 1
            return document

        # 逐行迭代，不调用 read_text（避免整篇入内存）
        with open(file_path, encoding=encoding, errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                buffer.append(line)
                buffer_chars += len(line)
                if buffer_chars >= TEXT_MAX_CHUNK_CHARS:
                    yield _flush()

        if buffer:
            yield _flush()
