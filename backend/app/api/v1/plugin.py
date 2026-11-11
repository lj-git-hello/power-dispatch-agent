"""插件清单路由（通用层）。

后端是端点路径与演示身份的唯一真相源：前端启动时拉取本端点，按插件名
与本地注册表匹配并采用后端下发的数据，消除前后端各自硬编码的漂移。

下发路径均相对 /api（与前端 http baseURL 对齐）。
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.plugin.loader import PluginLoader

plugin_router = APIRouter(prefix="/plugin", tags=["Universal-Plugin"])


class PluginIdentityResponse(BaseModel):
    """插件声明的演示身份（供通用外壳的身份切换器渲染）。"""

    id: str = Field(..., description="登录账号 ID")
    label: str = Field(..., description="展示名")
    role: str = Field(..., description="角色标识（语义由插件解释）")


class PluginManifestResponse(BaseModel):
    """活跃插件的对外描述。"""

    name: str = Field(..., description="插件唯一名（须与前端插件目录名一致）")
    version: str = Field(..., description="插件语义化版本")
    endpoints: dict[str, str] = Field(
        default_factory=dict,
        description="端点路径字典（相对 /api，如 /v1/sample-biz/tasks）",
    )
    identities: list[PluginIdentityResponse] = Field(
        default_factory=list,
        description="演示身份列表（供通用外壳身份切换器）",
    )


@plugin_router.get("/manifest", response_model=PluginManifestResponse)
async def get_plugin_manifest() -> PluginManifestResponse:
    """返回当前生效插件的名称、版本、端点路径与演示身份。"""
    manifest = PluginLoader.active()
    return PluginManifestResponse(
        name=manifest.name,
        version=manifest.version,
        endpoints=manifest.endpoints,
        identities=[
            PluginIdentityResponse(
                id=item.user_id,
                label=item.name,
                role=item.role,
            )
            for item in manifest.identities
        ],
    )


__all__ = [
    "PluginIdentityResponse",
    "PluginManifestResponse",
    "plugin_router",
]
