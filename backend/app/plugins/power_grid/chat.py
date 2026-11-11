"""电网安规问答对话处理器（垂直插件）。

复用通用 RAG 检索（core.rag）与通用 LLM 工厂（core.llm），
输出统一的扁平 A2UI 事件：

- token：LLM 增量文本（逐字推流）
- ui_card：规程引文卡片（card_type=power_grid_citations）

SSE 分帧、消息落库与执行留痕全部由通用对话网关负责，本模块只管语义。
LLM 不可用 / 调用异常时走确定性降级（召回条目直出），绝不卡死。
"""

import time
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import build_chat_model, resolve_model_name
from app.core.plugin.manifest import ChatContext
from app.core.rag.vector_service import VectorStoreService
from app.plugins.power_grid.constants import (
    POWER_CARD_TYPE_CITATIONS,
    POWER_RAG_BIZ_TAG,
)
from app.schemas.a2ui import A2UIEventType, AgentChatEvent, AgentChatRequest

# ---- 检索参数 ----
RAG_TOP_K = 3
RAG_MIN_SIMILARITY = 0.3

# ---- 模型参数 ----
QA_TEMPERATURE = 0.1
# Trace 节点名（通用留痕口径，与业务图节点名无关）
CHAT_TRACE_NODE = "chat.stream"

# ---- 固定文案 ----
NO_RESULT_ANSWER = (
    "知识库中暂未检索到与该问题直接相关的规程依据，"
    "请核实问题或联系管理员确认。"
)
EMPTY_QUESTION_MESSAGE = "消息内容为空，请输入需要咨询的安规问题。"
DEGRADED_ANSWER_HEADER = "依据规程要求，相关条款如下："

# 通用问答系统提示（仅依据参考条目作答，强制标注出处，无依据则拒答）
QA_SYSTEM_PROMPT = (
    "你是一个严谨的电力安规知识问答助手。请严格且仅依据用户提供的【参考条目】"
    "回答问题，不得使用参考条目之外的信息或自行推断。回答中需标注所引用条目的"
    "出处编号与章节。若参考条目不足以回答问题，请明确说明现有资料中没有相关依据，"
    "不要编造。"
)


def _build_citations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把检索结果整理为引文条目（结构化，可直接下发为卡片负载）。"""
    citations: list[dict[str, Any]] = []
    for row in rows:
        citations.append(
            {
                "doc_code": row.get("doc_code"),
                "section_title": row.get("section_title"),
                "content": row.get("content"),
                "similarity": round(float(row.get("similarity") or 0.0), 4),
            }
        )
    return citations


def _build_context(citations: list[dict[str, Any]]) -> str:
    """把引文组装为提供给模型的参考文本。"""
    blocks = []
    for index, item in enumerate(citations, start=1):
        title = item.get("section_title")
        blocks.append(
            f"[条目{index}] 出处：{item.get('doc_code')}"
            f"{' / ' + title if title else ''}\n"
            f"内容：{item.get('content')}"
        )
    return "\n\n".join(blocks)


def _build_degraded_answer(citations: list[dict[str, Any]]) -> str:
    """大模型不可用 / 调用失败时的确定性带引文答复。"""
    lines = [DEGRADED_ANSWER_HEADER]
    for item in citations:
        title = item.get("section_title")
        source = f"【{item.get('doc_code')}{(' / ' + title) if title else ''}】"
        lines.append(f"{source}\n{item.get('content')}")
    return "\n".join(lines)


def _citation_event(citations: list[dict[str, Any]]) -> AgentChatEvent:
    """构造引文卡片事件。"""
    return AgentChatEvent(
        type=A2UIEventType.UI_CARD,
        card_type=POWER_CARD_TYPE_CITATIONS,
        data={"citations": citations},
    )


async def power_grid_chat_handler(
    context: ChatContext,
    request: AgentChatRequest,
) -> AsyncIterator[AgentChatEvent]:
    """安规 RAG 问答：召回规程 → 流式生成 → 附引文卡片。"""
    question = (request.message or "").strip()
    if not question:
        yield AgentChatEvent(
            type=A2UIEventType.ERROR,
            message=EMPTY_QUESTION_MESSAGE,
        )
        return

    # ---- 1. 召回规程条款（检索异常不阻断，转确定性降级） ----
    try:
        rows = await VectorStoreService().search_advanced(
            query=question,
            biz_tag=POWER_RAG_BIZ_TAG,
            top_k=RAG_TOP_K,
            min_similarity=RAG_MIN_SIMILARITY,
        )
    except Exception:  # noqa: BLE001 —— 检索不可用时降级为"无依据"答复
        rows = []

    if not rows:
        yield AgentChatEvent(type=A2UIEventType.TOKEN, content=NO_RESULT_ANSWER)
        return

    citations = _build_citations(rows)

    # ---- 2. 大模型生成（不可用则确定性降级） ----
    llm = build_chat_model(temperature=QA_TEMPERATURE)
    if llm is None:
        yield AgentChatEvent(
            type=A2UIEventType.TOKEN,
            content=_build_degraded_answer(citations),
        )
        yield _citation_event(citations)
        return

    messages = [
        SystemMessage(content=QA_SYSTEM_PROMPT),
        HumanMessage(
            content=f"问题：{question}\n\n参考条目：\n{_build_context(citations)}"
        ),
    ]

    started = time.perf_counter()
    prompt_tokens = 0
    completion_tokens = 0
    produced = False
    error_text: str | None = None

    try:
        async for chunk in llm.astream(messages):
            usage = getattr(chunk, "usage_metadata", None) or {}
            prompt_tokens = max(prompt_tokens, int(usage.get("input_tokens") or 0))
            completion_tokens = max(
                completion_tokens, int(usage.get("output_tokens") or 0)
            )
            text = chunk.content if isinstance(chunk.content, str) else ""
            if text:
                produced = True
                yield AgentChatEvent(type=A2UIEventType.TOKEN, content=text)
    except Exception as exc:  # noqa: BLE001 —— 超时/限流统一降级
        error_text = f"{type(exc).__name__}: {exc}"
        if not produced:
            yield AgentChatEvent(
                type=A2UIEventType.TOKEN,
                content=_build_degraded_answer(citations),
            )

    latency_ms = int((time.perf_counter() - started) * 1000)

    # ---- 3. 执行留痕（写入由通用层完成，本模块只上报观测数据） ----
    if context.trace_sink is not None:
        await context.trace_sink.record(
            node_name=CHAT_TRACE_NODE,
            model_name=resolve_model_name(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            error_log=error_text,
        )

    if error_text is not None and produced:
        yield AgentChatEvent(
            type=A2UIEventType.ERROR,
            message="回答生成中断，已保留已输出部分。",
        )

    yield _citation_event(citations)


__all__ = ["CHAT_TRACE_NODE", "power_grid_chat_handler"]
