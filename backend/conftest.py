"""本地测试套件统一配置（backend/tests/ 目录内容不入库，仅本地验证使用）。

一、事件循环统一为「会话级」
    SQLAlchemy / asyncpg 连接池是**模块级全局单例**（app.core.database.async_engine）。
    若 pytest-asyncio 为不同用例分配不同事件循环，连接池里的连接会被跨循环复用，
    触发 asyncpg 的
        RuntimeError: got Future attached to a different loop
    生产运行时是「单进程单事件循环」，因此测试同样统一到**会话级事件循环**，
    既消除跨循环污染，也让测试语义与生产一致。

二、遗留脚本排除收集
    test_dualmode_graph.py / test_postgres_checkpoint_flow.py 针对的是重构前
    已被删除的 app.agent 包（意图路由双模图：QA / PLAN_APPLY），插件化改造后
    业务图已收敛为 app/plugins/<biz>/graph.py 的单向状态机 + 独立 chat handler，
    两脚本的断言对象不复存在。文件保留在本地（仍可手动以脚本方式运行），
    但不参与 pytest 收集，避免导入期异常污染整套用例。
"""

import asyncio
import sys

# Windows 兼容：psycopg / asyncpg 在默认 Proactor 事件循环下不可用，
# 必须在任何事件循环被创建之前切换策略。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 注：事件循环作用域（会话级）统一配置在 backend/pytest.ini 中声明
#     —— pytest 9 的 Config.getini 只读取 ini 文件与 -o 覆盖项，
#        直接写 config.option.* 不会生效。


# 遗留脚本：不参与 pytest 收集（原因见模块 docstring）
collect_ignore = [
    "tests/test_dualmode_graph.py",
    "tests/test_postgres_checkpoint_flow.py",
]
