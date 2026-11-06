"""通用系统路由 —— 身份认证（登录 / 当前用户）。

属脚手架通用能力，不含任何垂直业务逻辑。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security import get_current_user
from app.services.acl import IAMGatewayAdapter

router = APIRouter(prefix="/auth", tags=["System-Auth"])


class LoginRequest(BaseModel):
    """登录请求：Mock 阶段以预置 user_id 直接换取 Token。"""

    user_id: str


@router.post("/login")
async def login(req: LoginRequest) -> dict:
    """以预置账号 user_id 签发 Token，并回带用户身份元数据。

    未知 user_id（Mock 账号不存在）由 IAM 网关抛 KeyError，
    这里统一转成 401。
    """
    try:
        token = IAMGatewayAdapter.create_access_token(req.user_id)
        user = IAMGatewayAdapter.verify_token(token)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"账号 {req.user_id} 不存在或无权登录。",
        )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
    }


@router.get("/me")
async def read_me(current_user: dict = Depends(get_current_user)) -> dict:
    """返回当前登录用户的身份元数据。"""
    return current_user