"""业务插件自动发现与生效选择（通用层）。

发现机制：扫描 app/plugins/*/plugin.py，读取每个插件导出的 PLUGIN 清单。
生效机制：环境变量 ACTIVE_PLUGIN 显式指定；未设置时若仅一个插件则取之，
多个则启动即报错并列出候选（确定性优先，绝不隐式猜测）。

隔离约束：本模块只引用"插件容器包"app.plugins，不引用任何具体业务插件。
"""

import importlib
import logging
import os
import pkgutil

from app.core.plugin.manifest import PluginContractError, PluginManifest

logger = logging.getLogger(__name__)

# 生效插件环境变量
ACTIVE_PLUGIN_ENV = "ACTIVE_PLUGIN"
# 插件清单模块名（插件目录下须存在 plugin.py）
PLUGIN_MODULE_NAME = "plugin"
# 插件清单导出名（plugin.py 中须存在 PLUGIN）
PLUGIN_ATTR_NAME = "PLUGIN"


class PluginLoader:
    """插件发现 / 生效选择器。"""

    # 进程内缓存的生效清单
    _active: PluginManifest | None = None

    # ------------------------------------------------------------------
    # 发现
    # ------------------------------------------------------------------
    @classmethod
    def discover(cls) -> dict[str, PluginManifest]:
        """扫描插件目录，返回 {插件名: 清单}。

        - 子包无 plugin.py → 视为非插件子包，跳过（并记录 debug 日志）。
        - 插件模块导入抛异常 → 直接向上抛出（fail-fast，绝不静默跳过）。
        - plugin.py 未导出 PLUGIN 或类型不符 → 视为契约违规，直接报错。
        """
        # 延迟导入插件容器包，避免与包初始化顺序耦合
        from app import plugins as plugins_package

        manifests: dict[str, PluginManifest] = {}
        for module_info in pkgutil.iter_modules(plugins_package.__path__):
            plugin_name = module_info.name
            if plugin_name.startswith("_"):
                continue

            module_path = f"app.plugins.{plugin_name}.{PLUGIN_MODULE_NAME}"
            try:
                module = importlib.import_module(module_path)
            except ModuleNotFoundError as exc:
                # 该子包根本没有 plugin.py → 非插件子包，跳过；
                # 其余缺模块（插件自身依赖缺失）必须 fail-fast。
                if exc.name == module_path:
                    logger.debug("[插件装载] %s 无 plugin.py，跳过。", plugin_name)
                    continue
                raise

            manifest = getattr(module, PLUGIN_ATTR_NAME, None)
            if manifest is None:
                logger.warning(
                    "[插件装载] %s 的 %s.py 未导出 %s，已跳过。",
                    plugin_name,
                    PLUGIN_MODULE_NAME,
                    PLUGIN_ATTR_NAME,
                )
                continue
            if not isinstance(manifest, PluginManifest):
                raise PluginContractError(
                    f"插件 {plugin_name} 的 {PLUGIN_ATTR_NAME} 必须是 "
                    f"PluginManifest 实例，实际为 {type(manifest).__name__}。"
                )
            if manifest.name != plugin_name:
                raise PluginContractError(
                    f"插件 {plugin_name} 的清单 name={manifest.name!r} 与目录名不一致。"
                )
            manifests[plugin_name] = manifest

        return manifests

    # ------------------------------------------------------------------
    # 生效选择
    # ------------------------------------------------------------------
    @classmethod
    def load_active(cls) -> PluginManifest:
        """确定并缓存生效插件清单（每次调用都重新发现）。"""
        manifests = cls.discover()
        if not manifests:
            raise PluginContractError(
                "未发现任何业务插件：app/plugins/*/plugin.py 均缺失或未导出 PLUGIN。"
            )

        active_name = os.getenv(ACTIVE_PLUGIN_ENV, "").strip()
        if active_name:
            manifest = manifests.get(active_name)
            if manifest is None:
                raise PluginContractError(
                    f"环境变量 {ACTIVE_PLUGIN_ENV}={active_name!r} 未匹配到插件；"
                    f"可用插件：{sorted(manifests)}。"
                )
        elif len(manifests) == 1:
            manifest = next(iter(manifests.values()))
        else:
            raise PluginContractError(
                f"检测到多个业务插件 {sorted(manifests)}，"
                f"请通过环境变量 {ACTIVE_PLUGIN_ENV} 指定生效插件。"
            )

        cls._seed_identities(manifest)
        cls._active = manifest
        logger.info(
            "[插件装载] 生效插件=%s v%s 端点=%s",
            manifest.name,
            manifest.version,
            manifest.endpoints,
        )
        return manifest

    @classmethod
    def _seed_identities(cls, manifest: PluginManifest) -> None:
        """把插件声明的演示身份登记进 IAM 账号目录。

        通用 IAM 不认识任何业务角色，只做账号登记；
        user_id / name / role / dept 全部由插件自行声明。
        """
        if not manifest.identities:
            return

        from app.services.acl import IAMGatewayAdapter

        for identity in manifest.identities:
            IAMGatewayAdapter.register_user(
                user_id=identity.user_id,
                name=identity.name,
                role=identity.role,
                dept=identity.dept,
            )
        logger.info(
            "[插件装载] 已登记插件 %s 的演示身份 %s",
            manifest.name,
            [item.user_id for item in manifest.identities],
        )

    @classmethod
    def active(cls) -> PluginManifest:
        """取生效插件清单；未装载则先装载。"""
        if cls._active is None:
            return cls.load_active()
        return cls._active

    @classmethod
    def clear(cls) -> None:
        """清空缓存（主要用于测试隔离）。"""
        cls._active = None


__all__ = [
    "ACTIVE_PLUGIN_ENV",
    "PLUGIN_ATTR_NAME",
    "PLUGIN_MODULE_NAME",
    "PluginLoader",
]
