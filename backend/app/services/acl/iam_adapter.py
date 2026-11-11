"""统一身份认证防腐适配器（IAM Anti-Corruption Adapter）。

当前为 Mock 实现：预置企业账号，下发 / 校验本地 JWT。
后续替换为对接企业 IAM / 统一权限平台时，仅需替换本文件内部实现，
对外保持 IAMGatewayAdapter 的静态方法签名不变。

形态与各业务插件的外部系统适配器对齐：无状态静态网关。
模块级 create_access_token / verify_access_token 为向后兼容别名，
旧脚本与测试无需改动。

安全约束：签名私钥仅从环境变量 JWT_SECRET_KEY 读取，严禁硬编码。
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

# ---- 常量（禁止魔法值） ----
JWT_SECRET_ENV = "JWT_SECRET_KEY"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12

# JWT 标准 / 自定义声明键
CLAIM_SUBJECT = "sub"
CLAIM_NAME = "name"
CLAIM_ROLE = "role"
CLAIM_DEPT = "dept"
CLAIM_ISSUED_AT = "iat"
CLAIM_EXPIRES_AT = "exp"

# 通用角色占位（语义由各业务插件自行解释，IAM 只做透传）
ROLE_DEFAULT = "DEFAULT"

# ---- 演示账号目录 ----
# 通用 IAM 只维护"账号目录"，不解释任何业务角色；
# 各业务插件在自身清单中声明演示身份，由插件装载器登记到这里。
MOCK_USERS: dict[str, dict[str, str]] = {
    "demo_user": {
        "user_id": "demo_user",
        "name": "演示用户",
        "role": ROLE_DEFAULT,
        "dept": "",
    },
}


def _get_secret_key() -> str:
    """读取 JWT 签名密钥；缺失即 fail-fast，拒绝在无密钥下签发。"""
    secret = os.getenv(JWT_SECRET_ENV)
    if not secret:
        raise RuntimeError(
            f"环境变量 {JWT_SECRET_ENV} 未配置，无法签发 / 校验 JWT"
        )
    return secret


class IAMGatewayAdapter:
    """统一身份认证网关防腐适配器（Mock 实现，无状态静态网关）。"""

    @staticmethod
    def register_user(
        user_id: str,
        name: str,
        role: str,
        dept: str = "",
    ) -> None:
        """登记演示账号（由插件装载器在启动时调用）。

        通用 IAM 只维护账号目录；具体业务身份由插件在清单中声明，
        通用层不预置任何业务角色名或部门名。
        """
        MOCK_USERS[user_id] = {
            "user_id": user_id,
            "name": name,
            "role": role,
            "dept": dept,
        }

    @staticmethod
    def create_access_token(user_id: str) -> str:
        """为预置账号下发 12 小时有效期的标准 JWT。

        Claims：sub(user_id)、name、role、dept、iat、exp。
        未知 user_id 抛出 KeyError。
        """
        user = MOCK_USERS[user_id]

        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            CLAIM_SUBJECT: user["user_id"],
            CLAIM_NAME: user["name"],
            CLAIM_ROLE: user["role"],
            CLAIM_DEPT: user["dept"],
            CLAIM_ISSUED_AT: now,
            CLAIM_EXPIRES_AT: now
            + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        }

        return jwt.encode(payload, _get_secret_key(), algorithm=JWT_ALGORITHM)

    @staticmethod
    def verify_token(token: str) -> dict[str, Any]:
        """解码并校验 JWT 签名与有效期。

        成功返回声明字典；过期抛出 jwt.ExpiredSignatureError，
        签名非法 / 格式错误抛出 jwt.InvalidTokenError。
        """
        return jwt.decode(
            token,
            _get_secret_key(),
            algorithms=[JWT_ALGORITHM],
            options={"require": [CLAIM_SUBJECT, CLAIM_EXPIRES_AT]},
        )

    @staticmethod
    def verify_access_token(token: str) -> dict[str, Any]:
        """verify_token 的向后兼容别名。"""
        return IAMGatewayAdapter.verify_token(token)


# ---- 模块级向后兼容别名：旧脚本 / 旧测试可继续按函数方式导入调用 ----
create_access_token = IAMGatewayAdapter.create_access_token
verify_access_token = IAMGatewayAdapter.verify_access_token