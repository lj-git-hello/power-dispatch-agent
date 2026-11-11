"""插件隔离静态检查脚本（CI / 提交前门禁）。

断言"AI 资产与业务完全物理隔离"这一硬约束在**代码层面**成立：
通用底座目录不得出现任何垂直业务词汇（电网检修、调度令、电压等级、
外部系统名、业务卡片类型等），也不得 import 任何具体业务插件。

检查范围：
- backend/app/core/          通用底座（工作流中枢 / RAG 框架 / 插件装载器）
- backend/app/schemas/a2ui.py 通用 A2UI 契约
- backend/app/api/v1/agent.py 通用对话网关
- backend/app/api/v1/plugin.py 通用插件清单路由
- backend/app/services/acl/    防腐层通用契约
- frontend/src/core/          前端通用底座

用法：
    python scripts/check_plugin_isolation.py
退出码：0 = 通过；1 = 存在业务词汇泄漏。
"""

import re
import sys
from pathlib import Path

# backend/ 注入 sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

REPO_DIR = BACKEND_DIR.parent
FRONTEND_CORE = REPO_DIR / "frontend" / "src" / "core"

# ---- 受检目录（通用底座） ----
SCAN_TARGETS: tuple[Path, ...] = (
    BACKEND_DIR / "app" / "core",
    BACKEND_DIR / "app" / "schemas" / "a2ui.py",
    BACKEND_DIR / "app" / "api" / "v1" / "agent.py",
    BACKEND_DIR / "app" / "api" / "v1" / "plugin.py",
    BACKEND_DIR / "app" / "services" / "acl",
    FRONTEND_CORE,
)

# ---- 业务词汇黑名单（正则，忽略大小写） ----
# 命中即视为隔离违规：底座一旦出现这些词，换业务就需要改底座。
BUSINESS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"power[_-]grid", "业务插件名"),
    (r"power[_-]dispatch", "业务路由前缀"),
    (r"\bOMS\b", "外部业务系统 OMS"),
    (r"\bSCADA\b", "外部业务系统 SCADA"),
    (r"dispatcher_audit", "业务卡片类型"),
    (r"permit_result", "业务卡片类型"),
    (r"power_grid_citations", "业务卡片类型"),
    (r"变电站", "电网业务名词"),
    (r"调度令", "电网业务名词"),
    (r"检修", "电网业务名词"),
    (r"安规", "电网业务名词"),
    (r"停电", "电网业务名词"),
    (r"核签", "电网业务名词"),
    (r"许可令", "电网业务名词"),
    (r"运检", "电网业务名词"),
    (r"值班长", "电网业务名词"),
    (r"电压等级", "电网业务名词"),
    (r"\bkV\b", "电网业务名词"),
    (r"\bDISPATCHER\b", "电网业务角色"),
    (r"\bAPPLICANT\b", "电网业务角色"),
    (r"\bdispatcher_lead\b", "电网业务演示账号"),
    (r"\bapplicant_0\d\b", "电网业务演示账号"),
    (r"腊山|玉皇顶|地调控制中心", "电网业务组织名"),
)

# ---- 允许出现的"说明性"豁免 ----
# 这些词只允许出现在明确标注为示例/反例的注释里，且必须带豁免标记。
EXEMPTION_MARKER = "@isolation-exempt"

TEXT_SUFFIXES = frozenset({".py", ".ts", ".vue"})
SKIP_DIR_NAMES = frozenset({"__pycache__", "node_modules", "dist", ".git"})

COMPILED = tuple((re.compile(pattern, re.IGNORECASE), label) for pattern, label in BUSINESS_PATTERNS)


def iter_files(target: Path):
    """遍历受检目标下的所有文本文件。"""
    if target.is_file():
        yield target
        return
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        yield path


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """返回 [(行号, 命中词, 标签)]。"""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    hits: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if EXEMPTION_MARKER in line:
            continue
        for pattern, label in COMPILED:
            matched = pattern.search(line)
            if matched:
                hits.append((lineno, matched.group(0), label))
                break
    return hits


def main() -> int:
    violations: list[tuple[Path, int, str, str]] = []
    scanned = 0

    for target in SCAN_TARGETS:
        if not target.exists():
            print(f"[隔离检查] 跳过不存在的目标：{target}")
            continue
        for path in iter_files(target):
            scanned += 1
            for lineno, word, label in scan_file(path):
                violations.append((path, lineno, word, label))

    print(f"[隔离检查] 已扫描 {scanned} 个通用底座文件。")

    if not violations:
        print("[隔离检查] 通过：通用底座未检出任何业务词汇。")
        return 0

    print(f"[隔离检查] 失败：检出 {len(violations)} 处业务词汇泄漏。")
    for path, lineno, word, label in violations:
        try:
            shown = path.relative_to(REPO_DIR)
        except ValueError:
            shown = path
        print(f"  - {shown}:{lineno} 命中「{word}」（{label}）")
    print(
        "整改要求：业务词汇必须下沉到 app/plugins/<biz>/ 与 "
        "frontend/src/plugins/<biz>/，通用底座不得感知业务语义。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
