"""通用挂起记录归档 CLI（运维脚本）。

通用中枢表的挂起队列（等待人工介入）是"只增不减"的工作队列：
记录一旦写入，若无人核准就永远不会离开队列。历史遗留 / 测试残留会
永久沉在审批人池里。本脚本提供统一入口把这类记录**归档**（软删除），
而非物理删除，以保留审计链路。

默认 dry-run：只打印将被归档的记录，确认无误后再加 --apply 落库。

用法：
    python scripts/archive_stale_pending.py --list
    python scripts/archive_stale_pending.py --before 2026-11-11T08:31:00
    python scripts/archive_stale_pending.py --thread-id <id> --thread-id <id>
    python scripts/archive_stale_pending.py --before 2026-11-11T08:31:00 --apply
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Windows 兼容：数据库链路含 psycopg，须在事件循环创建前切换策略
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 将 backend/ 注入 sys.path（脚本位于 backend/scripts/，parents[1] 指向 backend/）
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

# 显式加载 backend/.env，不依赖运行时工作目录
load_dotenv(BACKEND_DIR / ".env")

from app.core.workflow.thread_mapping_store import ThreadMappingStore


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="归档未再需要人工介入的历史挂起记录（软删除，保留审计链路）。"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出全部未归档的挂起记录（可与 --before / --thread-id 组合）。",
    )
    parser.add_argument(
        "--before",
        default="",
        help="仅处理创建时间早于该时刻的记录，格式 YYYY-MM-DDTHH:MM:SS。",
    )
    parser.add_argument(
        "--thread-id",
        action="append",
        default=[],
        dest="thread_ids",
        help="仅处理指定 thread_id（可重复传入）。",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正执行归档写入；缺省为 dry-run，仅预览。",
    )
    return parser


def _parse_before(raw: str) -> datetime | None:
    """解析 --before 时间戳；空串返回 None（不限时间）。"""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SystemExit(f"错误：--before 时间格式非法 -> {raw}（{exc}）")


async def _collect_targets(args: argparse.Namespace) -> list[dict]:
    """汇总本次需要归档的记录（已过滤掉已归档项）。"""
    if args.thread_ids:
        # 指定 ID 场景：逐条读取（不过滤状态——指定归档的是记录本身）
        targets: list[dict] = []
        for thread_id in args.thread_ids:
            mapping = await ThreadMappingStore.get(thread_id)
            if mapping is None:
                print(f"[跳过] 记录不存在：{thread_id}")
                continue
            if mapping.get("is_archived"):
                print(f"[跳过] 记录已是归档态：{thread_id}")
                continue
            targets.append(mapping)
        return targets

    before = _parse_before(args.before)
    return await ThreadMappingStore.list_pending(before)


def _print_targets(targets: list[dict]) -> None:
    print(f"[归档预览] 命中 {len(targets)} 条待归档记录：")
    for item in targets:
        print(
            f"  - {item.get('thread_id')}"
            f"  创建于 {item.get('created_at')}"
            f"  状态 {item.get('status')}"
            f"  指派角色 {item.get('assigned_role')}"
        )


async def _amain() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not args.list and not args.before and not args.thread_ids:
        parser.print_help()
        print("\n提示：至少指定 --list / --before / --thread-id 之一。")
        return

    targets = await _collect_targets(args)
    _print_targets(targets)

    if not targets:
        print("[归档预览] 无命中记录，无需处理。")
        return

    if not args.apply:
        print("\n[归档预览] dry-run 模式，未做任何写入；确认无误后追加 --apply 执行。")
        return

    archived = await ThreadMappingStore.archive_many(
        [str(item["thread_id"]) for item in targets]
    )
    print(f"\n[归档执行] 已归档 {len(archived)} 条：")
    for thread_id in archived:
        print(f"  - {thread_id}")


if __name__ == "__main__":
    asyncio.run(_amain())
