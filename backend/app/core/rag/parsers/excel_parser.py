"""电子表格流式解析器：.xlsx 用 openpyxl(read_only)，.csv 用标准库 csv。

逐行读入，按固定行数分批产出；每批内复用表头拼成"表头: 值"短句，
既不丢失列名语义，也不将整表物化到内存。
"""

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.core.rag.parsers.base import BaseParser, ParsedDocument

KEY_VALUE_SEPARATOR = ": "
CELL_SEPARATOR = ", "
ROW_SEPARATOR = "\n"

# 单个产出块包含的数据行数
EXCEL_ROW_BATCH_SIZE = 100

CSV_CANDIDATE_ENCODINGS = ("utf-8-sig", "gbk")

META_SHEET_KEY = "sheet"
_ROW_NUMBER_START = 1


def _row_to_sentence(headers: list[str], cells: tuple[Any, ...]) -> str:
    """把一行按表头拼成"表头: 值"，跳过空值。"""
    parts: list[str] = []
    for header, value in zip(headers, cells):
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        parts.append(f"{header}{KEY_VALUE_SEPARATOR}{text}")
    return CELL_SEPARATOR.join(parts)


def _is_empty_row(row: Any) -> bool:
    """判定一行是否全部为空。"""
    return not any(
        cell is not None and str(cell).strip() for cell in row
    )


def _emit_sheet(
    title: str,
    source_path: str,
    doc_type: str,
    sheet_name: str,
    numbered_rows: Iterator[tuple[int, Any]],
) -> Iterator[ParsedDocument]:
    """消费 (行号, 行) 流，按行批次 yield ParsedDocument。"""
    headers: list[str] | None = None

    batch_sentences: list[str] = []
    batch_index = 0
    batch_start_row = 0
    last_row = 0

    def _flush(end_row: int) -> ParsedDocument:
        return ParsedDocument(
            title=f"{title}#{sheet_name}#batch{batch_index}",
            content=ROW_SEPARATOR.join(batch_sentences),
            source_path=source_path,
            doc_type=doc_type,
            metadata={
                META_SHEET_KEY: sheet_name,
                "batch": batch_index,
                "start_row": batch_start_row,
                "end_row": end_row,
                "row_count": len(batch_sentences),
            },
        )

    for row_number, row in numbered_rows:
        last_row = row_number
        # 首条非空行作为表头
        if headers is None:
            if _is_empty_row(row):
                continue
            headers = [str(c).strip() for c in row]
            continue

        if _is_empty_row(row):
            continue

        if not batch_sentences:
            batch_index += 1
            batch_start_row = row_number

        batch_sentences.append(_row_to_sentence(headers, tuple(row)))

        if len(batch_sentences) >= EXCEL_ROW_BATCH_SIZE:
            document = _flush(row_number)
            batch_sentences = []
            yield document

    if batch_sentences:
        yield _flush(last_row)


def _iter_xlsx(file_path: str) -> Iterator[ParsedDocument]:
    """read_only 逐行读取每个工作表并分批产出。"""
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    name = Path(file_path).name

    try:
        for worksheet in workbook.worksheets:
            numbered_rows = (
                (index, list(row))
                for index, row in enumerate(
                    worksheet.iter_rows(values_only=True),
                    start=_ROW_NUMBER_START,
                )
            )
            yield from _emit_sheet(
                title=name,
                source_path=file_path,
                doc_type="xlsx",
                sheet_name=worksheet.title,
                numbered_rows=numbered_rows,
            )
    finally:
        workbook.close()


def _sniff_csv_encoding(file_path: str) -> str:
    """读取小前缀判定编码，避免"边读边切"导致的重复产出。"""
    with open(file_path, "rb") as handle:
        prefix = handle.read(4096)
    for encoding in CSV_CANDIDATE_ENCODINGS:
        try:
            prefix.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return CSV_CANDIDATE_ENCODINGS[0]


def _read_csv_numbered_rows(file_path: str) -> Iterator[tuple[int, list[str]]]:
    """以嗅探确定的编码逐行产出 (行号, 行)，异常字节容错替换。"""
    encoding = _sniff_csv_encoding(file_path)
    with open(
        file_path, encoding=encoding, errors="replace", newline=""
    ) as handle:
        for index, row in enumerate(csv.reader(handle), start=_ROW_NUMBER_START):
            yield index, row


def _iter_csv(file_path: str) -> Iterator[ParsedDocument]:
    """读取单个 CSV 并分批产出。"""
    name = Path(file_path).name
    yield from _emit_sheet(
        title=name,
        source_path=file_path,
        doc_type="csv",
        sheet_name="Sheet1",
        numbered_rows=_read_csv_numbered_rows(file_path),
    )


class ExcelParser(BaseParser):
    """.xlsx / .csv 流式解析器。"""

    def iter_parse(self, file_path: str) -> Iterator[ParsedDocument]:
        suffix = Path(file_path).suffix.lower()
        if suffix == ".csv":
            yield from _iter_csv(file_path)
        else:
            yield from _iter_xlsx(file_path)
