""".docx 流式解析器：段落按阈值聚合，表格各自转 Markdown 独立产出。

库限制说明：python-docx 的 ``Document(path)`` 会将整个 docx(zip) 解析为
lxml 树，无法在磁盘读取层做到惰性；本解析器的流式化覆盖"内容聚合"层——
不再把全部块 join 成一个巨型字符串，而是按批 / 按表 yield，控制驻留文本量。
消费完成（生成器耗尽或被 close）后 document 局部引用即释放。
"""

from collections.abc import Iterator
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.rag.parsers.base import BaseParser, ParsedDocument

MD_COLUMN_SEPARATOR = "|"
MD_ALIGNMENT_DASH = "---"

# 段落聚合块的最大字符数
DOCX_MAX_PARA_CHARS = 2000

BLOCK_TYPE_PARAGRAPH = "paragraph"
BLOCK_TYPE_TABLE = "table"


def _table_to_markdown(table: Table) -> str:
    """将 Word 表格逐行转换为 Markdown 表格字符串。"""
    rows = table.rows
    if not rows:
        return ""

    def _row_cells(row) -> list[str]:
        return [cell.text.strip().replace("\n", " ") for cell in row.cells]

    header = _row_cells(rows[0])
    lines = [
        f"{MD_COLUMN_SEPARATOR} {MD_COLUMN_SEPARATOR.join(header)} {MD_COLUMN_SEPARATOR}",
        f"{MD_COLUMN_SEPARATOR} {MD_COLUMN_SEPARATOR.join(MD_ALIGNMENT_DASH for _ in header)} {MD_COLUMN_SEPARATOR}",
    ]
    for row in rows[1:]:
        cells = _row_cells(row)
        lines.append(
            f"{MD_COLUMN_SEPARATOR} {MD_COLUMN_SEPARATOR.join(cells)} {MD_COLUMN_SEPARATOR}"
        )
    return "\n".join(lines)


class DocxParser(BaseParser):
    """.docx 流式解析器。"""

    def iter_parse(self, file_path: str) -> Iterator[ParsedDocument]:
        document = Document(file_path)
        name = Path(file_path).name

        paragraph_buffer: list[str] = []
        paragraph_chars = 0
        block_index = 0

        def _flush_paragraphs() -> Iterator[ParsedDocument]:
            nonlocal block_index, paragraph_buffer, paragraph_chars
            if not paragraph_buffer:
                return
            block_index += 1
            content = "\n\n".join(paragraph_buffer)
            yield ParsedDocument(
                title=f"{name}#block{block_index}",
                content=content,
                source_path=file_path,
                doc_type="docx",
                metadata={
                    "block_index": block_index,
                    "block_type": BLOCK_TYPE_PARAGRAPH,
                },
            )
            paragraph_buffer = []
            paragraph_chars = 0

        # 按正文顺序产出 Paragraph / Table，保持语义上下文
        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    continue
                paragraph_buffer.append(text)
                paragraph_chars += len(text)
                if paragraph_chars >= DOCX_MAX_PARA_CHARS:
                    yield from _flush_paragraphs()
            elif isinstance(item, Table):
                # 表格前先冲刷已聚合段落，保证"段落→表格"的文档顺序
                yield from _flush_paragraphs()
                markdown_table = _table_to_markdown(item)
                if markdown_table:
                    block_index += 1
                    yield ParsedDocument(
                        title=f"{name}#block{block_index}",
                        content=markdown_table,
                        source_path=file_path,
                        doc_type="docx",
                        metadata={
                            "block_index": block_index,
                            "block_type": BLOCK_TYPE_TABLE,
                        },
                    )

        # 收尾：剩余段落
        yield from _flush_paragraphs()
