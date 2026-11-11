"""电网业务插件清单（垂直插件入口）。

通用底座只认 PluginManifest，不认任何业务细节：
新增业务 = 新增一个插件目录（含 plugin.py），底座零改动。
"""

from app.core.plugin.manifest import PluginIdentity, PluginManifest
from app.plugins.power_grid.chat import power_grid_chat_handler
from app.plugins.power_grid.constants import (
    POWER_ENDPOINT_APPLY,
    POWER_ENDPOINT_MESSAGES,
    POWER_ENDPOINT_RESUME,
    POWER_ENDPOINT_TASKS,
    POWER_GRAPH_NAME,
    POWER_PLUGIN_NAME,
    POWER_PLUGIN_VERSION,
    POWER_ROLE_APPLICANT,
    POWER_ROLE_DISPATCHER,
    POWER_ROUTER_PREFIX,
)
from app.plugins.power_grid.graph import build_dispatch_graph
from app.plugins.power_grid.router import power_dispatch_router

# 插件清单（供 app.core.plugin.loader 发现）
PLUGIN = PluginManifest(
    name=POWER_PLUGIN_NAME,
    version=POWER_PLUGIN_VERSION,
    router=power_dispatch_router,
    router_prefix=POWER_ROUTER_PREFIX,
    graph_factory=build_dispatch_graph,
    graph_name=POWER_GRAPH_NAME,
    chat_handler=power_grid_chat_handler,
    endpoint_paths={
        "tasks": POWER_ENDPOINT_TASKS,
        "messages": POWER_ENDPOINT_MESSAGES,
        "resume": POWER_ENDPOINT_RESUME,
        "apply": POWER_ENDPOINT_APPLY,
    },
    # 演示身份：通用外壳的身份切换器据此渲染，Mock IAM 据此登记账号
    identities=(
        PluginIdentity(
            user_id="applicant_01",
            name="张三",
            role=POWER_ROLE_APPLICANT,
            dept="运检一班",
        ),
        PluginIdentity(
            user_id="dispatcher_lead",
            name="王调度长",
            role=POWER_ROLE_DISPATCHER,
            dept="调度控制中心",
        ),
    ),
)

__all__ = ["PLUGIN"]
