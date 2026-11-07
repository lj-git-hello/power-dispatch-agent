"""指定文件精确 / 覆盖更新入库 CLI（通用 RAG 运维脚本）。

对一批指定文件执行"流式解析 → 语义切片 → 批量入库"。
--overwrite 时先将同 doc_code 旧切片软废止（is_active=FALSE，保留可追溯），
再写入新版本。

用法：
    python scripts/rag_ingest_file.py --files a.md b.docx \\
        --biz-tag 220kV --doc-code DL-408-2021 [--doc-version v1.0] [--overwrite]
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Windows 兼容
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 将 backend/ 注入 sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

from app.core.rag.chunking import RecursiveSemanticChunker
from app.core.rag.parsers import iter_file
from app.core.rag.vector_service import VectorStoreService

DEFAULT_DOC_VERSION = "v1.0"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将指定文件精确入库，支持覆盖更新（软废止旧版）。"
    )
    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        help="文件路径列表，支持同时传入多个",
    )
    parser.add_argument(
        "--biz-tag", required=True, help="业务分类标签，如 220kV"
    )
    parser.add_argument(
        "--doc-code", required=True, help="规程编码，如 DL-408-2021"
    )
    parser.add_argument(
        "--doc-version",
        default=DEFAULT_DOC_VERSION,
        help=f"规程版本（默认 {DEFAULT_DOC_VERSION}）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖更新：先软废止同 doc_code 既有切片再写入",
    )
    return parser


async def _ingest_files(args: argparse.Namespace) -> None:
    store = VectorStoreService()

    deactivated = 0
    if args.overwrite:
        deactivated = await store.soft_delete_document(args.doc_code)
        print(
            f"[覆盖更新] doc_code={args.doc_code} 已软废止旧切片 {deactivated} 条"
            "（is_active=FALSE，旧版本保留可追溯）"
        )

    processed_files = 0
    total_inserted = 0

    # 复用默认切分参数（500/50）；本脚本职责在入库编排而非调参
    chunker = RecursiveSemanticChunker()

    for path in args.files:
        try:
            sections = iter_file(path)
            chunks = chunker.iter_split_sections(
                sections, args.doc_code, args.biz_tag
            )
            inserted = await store.batch_upsert_chunks(
                chunks, doc_version=args.doc_version
            )
            processed_files += 1
            total_inserted += inserted
            print(f"文件 {path}：新插入切片 {inserted} 条")
        except Exception as exc:  # noqa: BLE001 —— 单文件失败不中断其余文件
            print(f"[Warning] 跳过损坏文件 {path}: {exc}")

    print("\n========== RAG 文件入库汇总 ==========")
    print(f"处理文件数 : {processed_files}")
    print(f"切片插入数 : {total_inserted}")
    print(f"规程版本   : {args.doc_version}")
    if args.overwrite:
        print(f"软废止旧版 : {deactivated}")
    print("======================================")


async def _amain() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    missing = [path for path in args.files if not Path(path).is_file()]
    if missing:
        print("错误：以下文件不存在 ->")
        for path in missing:
            print(f"  {path}")
        sys.exit(2)

    await _ingest_files(args)


if __name__ == "__main__":
    asyncio.run(_amain())
