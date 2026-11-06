"""通用脚手架层 —— 鉴权门禁（与具体业务无关）。

提供：
- get_current_user：解析并校验 Bearer Token，返回标准用户载荷
- require_roles：角色门禁工厂，按允许角色列表做 RBAC 放行 / 拒绝

本模块对所有接入该脚手架的垂直业务通用，不包含任何电力业务概念。
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.services.acl import IAMGatewayAdapter

security = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """校验 Bearer Token 并返回标准用户载荷（sub/name/role/dept 等）。"""
    token = credentials.credentials
    try:
        # IAM 网关为本地静态方法（同步 CPU 操作），直接调用即可
        payload = IAMGatewayAdapter.verify_token(token)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已过期，请重新登录。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="凭证无效，无法通过身份校验。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def require_roles(allowed_roles: list[str]):
    """角色门禁工厂：返回一个依赖，仅当用户角色在允许列表内时放行，否则 403。"""

    def _check_role(
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足，禁止访问该资源。",
            )
        return current_user

    return _check_role
