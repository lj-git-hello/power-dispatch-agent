"""业务插件装配层（通用层，跨业务）。

对外暴露：
- PluginManifest：插件自描述清单（路由 / 状态机工厂 / 对话能力 / 端点路径）
- PluginLoader：插件自动发现与生效选择
- ChatContext / TraceSink：通用对话上下文与运行留痕契约
"""

from app.core.plugin.loader import PluginLoader
from app.core.plugin.manifest import (
    API_PREFIX,
    ChatContext,
    ChatHandler,
    PluginContractError,
    PluginManifest,
    TraceSink,
)

__all__ = [
    "API_PREFIX",
    "ChatContext",
    "ChatHandler",
    "PluginContractError",
    "PluginManifest",
    "PluginLoader",
    "TraceSink",
]
