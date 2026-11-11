"""通用大模型适配器工厂。

统一收口 ChatOpenAI 的厂商配置（模型名 / 基址 / Key / 超时 / 重试），
所有 LLM 调用点（通用问答路由、各业务插件对话处理器）共用同一入口：

- 密钥只来自环境变量，严禁硬编码；
- 未配置 Key 时返回 None，由调用方走确定性降级，绝不抛异常中断服务；
- 合规研判 / 知识问答统一低温（temperature ≤ 0.1）。
"""

import os

from langchain_openai import ChatOpenAI

# ---- 环境变量键 ----
ENV_API_KEY = "OPENAI_API_KEY"
ENV_BASE_URL = "OPENAI_BASE_URL"
ENV_MODEL_NAME = "OPENAI_MODEL_NAME"
ENV_TIMEOUT = "LLM_TIMEOUT"
ENV_MAX_RETRIES = "LLM_MAX_RETRIES"

# ---- 默认值 ----
DEFAULT_MODEL_NAME = "doubao-seed-2.1-lite"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 2
# 合规 / 规程问答统一低温
DEFAULT_TEMPERATURE = 0.1


def resolve_model_name() -> str:
    """当前生效的模型名（用于 Trace 留痕）。"""
    return os.getenv(ENV_MODEL_NAME, "").strip() or DEFAULT_MODEL_NAME


def build_chat_model(
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    model_name: str | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> ChatOpenAI | None:
    """构建 ChatOpenAI 实例；未配置 API Key 时返回 None。"""
    api_key = os.getenv(ENV_API_KEY, "").strip()
    if not api_key:
        return None

    resolved_timeout = (
        timeout
        if timeout is not None
        else float(os.getenv(ENV_TIMEOUT, "") or DEFAULT_TIMEOUT_SECONDS)
    )
    resolved_retries = (
        max_retries
        if max_retries is not None
        else int(os.getenv(ENV_MAX_RETRIES, "") or DEFAULT_MAX_RETRIES)
    )

    return ChatOpenAI(
        model=model_name or resolve_model_name(),
        api_key=api_key,
        base_url=os.getenv(ENV_BASE_URL, "").strip() or None,
        temperature=temperature,
        timeout=resolved_timeout,
        max_retries=resolved_retries,
    )


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_MAX_RETRIES",
    "ENV_MODEL_NAME",
    "ENV_TIMEOUT",
    "build_chat_model",
    "resolve_model_name",
]
