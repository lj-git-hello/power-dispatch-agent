"""统一身份认证防腐适配器（IAM Anti-Corruption Adapter）。

当前为 Mock 实现：预置企业账号，下发 / 校验本地 JWT。
后续替换为对接企业 IAM / 统一权限平台时，仅需替换本文件内部实现，
对外保持 create_access_token / verify_access_token 签名不变。

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

# 企业角色
ROLE_APPLICANT = "APPLICANT"
ROLE_DISPATCHER = "DISPATCHER"

# ---- 预置企业 Mock 账号 ----
# dept：提报人为所属班组，调度值班长为所属部门，统一映射到 token 的 dept 声明
MOCK_USERS: dict[str, dict[str, str]] = {
    "applicant_01": {
        "user_id": "applicant_01",
        "name": "张三",
        "role": ROLE_APPLICANT,
        "dept": "腊山运检工区",
    },
    "applicant_02": {
        "user_id": "applicant_02",
        "name": "李四",
        "role": ROLE_APPLICANT,
        "dept": "玉皇顶变电工区",
    },
    "dispatcher_lead": {
        "user_id": "dispatcher_lead",
        "name": "王调度长",
        "role": ROLE_DISPATCHER,
        "dept": "地调控制中心",
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
        CLAIM_EXPIRES_AT: now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }

    return jwt.encode(payload, _get_secret_key(), algorithm=JWT_ALGORITHM)


def verify_access_token(token: str) -> dict[str, Any]:
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