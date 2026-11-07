"""全量目录递归扫描入库 CLI（通用 RAG 运维脚本）。

递归遍历目标根目录，对受支持文档执行"流式解析 → 语义切片 → 批量入库"，
全链路生成器惰性产出；损坏文件仅 Warning 跳过，不中断整体。

用法：
    python scripts/rag_ingest_all.py --dir <目录> --biz-tag <标签>
"""

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

# Windows 兼容：入库链路含 psycopg，须在事件循环创建前切换策略
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 将 backend/ 注入 sys.path（脚本位于 backend/scripts/，parents[1] 指向 backend/）
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

# 显式加载 backend/.env，不依赖运行时工作目录
load_dotenv(BACKEND_DIR / ".env")

from app.core.rag.chunking import DocumentChunk, RecursiveSemanticChunker
from app.core.rag.parsers import iter_file
from app.core.rag.vector_service import VectorStoreService

# 受支持的文档后缀（含点、小写），与解析器工厂注册范围一致
SUPPORTED_SUFFIXES: frozenset[str] = frozenset(
    {".md", ".txt", ".docx", ".pdf", ".xlsx", ".csv"}
)

# 报表标签
REPORT_LABELS = {
    "scanned": "扫描文件数",
    "chunks": "生成切片数",
    "inserted": "实际插入数",
    "skipped": "幂等跳过数",
    "elapsed": "耗时(秒)",
}


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="递归扫描目录并将文档批量向量化入库。"
    )
    parser.add_argument(
        "--dir", required=True, help="目标根目录路径，如 ./plugins/power_grid/documents"
    )
    parser.add_argument(
        "--biz-tag", required=True, help="默认业务分类标签，如 220kV"
    )
    parser.add_argument(
        "--doc-code",
        default="",
        help="规程总编号；不传则以文件名去除后缀作为 doc_code",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=500, help="切片字符大小（默认 500）"
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=50,
        help="切片重叠字符大小（默认 50）",
    )
    return parser


class _CountedIterator:
    """透传切片并计数的迭代器：不改内容，不额外物化。

    用类而非"给生成器挂属性"——生成器对象无 __dict__，不能动态加属性。
    """

    def __init__(self, chunks: Iterator[DocumentChunk]) -> None:
        self._chunks = chunks
        self.count = 0

    def __iter__(self) -> "_CountedIterator":
        return self

    def __next__(self) -> DocumentChunk:
        chunk = next(self._chunks)
        self.count += 1
        return chunk


def _counted(chunks: Iterator[DocumentChunk]) -> _CountedIterator:
    """构造计数透传迭代器。"""
    return _CountedIterator(chunks)


async def _ingest_directory(args: argparse.Namespace) -> None:
    started_at = time.perf_counter()

    chunker = RecursiveSemanticChunker(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    store = VectorStoreService()

    scanned_files = 0
    total_chunks = 0
    total_inserted = 0

    for root, _dirs, files in os.walk(args.dir):
        for filename in sorted(files):
            path = os.path.join(root, filename)
            if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            scanned_files += 1

            try:
                sections = iter_file(path)
                doc_code = args.doc_code or Path(path).stem
                chunks = chunker.iter_split_sections(
                    sections, doc_code, args.biz_tag
                )
                counted = _counted(chunks)
                inserted = await store.batch_upsert_chunks(counted)

                total_chunks += counted.count
                total_inserted += inserted
            except Exception as exc:  # noqa: BLE001 —— 单文件失败不中断目录扫描
                print(f"[Warning] 跳过损坏文件 {path}: {exc}")

    idempotent_skipped = total_chunks - total_inserted
    elapsed = time.perf_counter() - started_at
    _print_report(
        scanned_files,
        total_chunks,
        total_inserted,
        idempotent_skipped,
        elapsed,
    )


def _print_report(
    scanned: int,
    chunks: int,
    inserted: int,
    skipped: int,
    elapsed: float,
) -> None:
    """输出对齐的统计报表。"""
    rows = [
        (REPORT_LABELS["scanned"], scanned),
        (REPORT_LABELS["chunks"], chunks),
        (REPORT_LABELS["inserted"], inserted),
        (REPORT_LABELS["skipped"], skipped),
        (REPORT_LABELS["elapsed"], f"{elapsed:.2f}"),
    ]
    label_width = max(len(label) for label, _ in rows)
    print("\n========== RAG 入库统计报表 ==========")
    for label, value in rows:
        print(f"{label:<{label_width}} : {value}")
    print("======================================")


async def _amain() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print(f"错误：目标目录不存在或非目录 -> {args.dir}")
        sys.exit(2)

    await _ingest_directory(args)


if __name__ == "__main__":
    asyncio.run(_amain())
