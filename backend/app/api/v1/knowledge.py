"""通用知识检索与问答路由（行业中立的脚手架能力）。

提供：
- POST /knowledge/search：多维精准向量检索
- POST /knowledge/ask：带条文引文出处的通用问答（大模型优先，确定性降级兜底）

本模块不包含任何行业专属词汇；垂直业务的差异完全由调用方传入的
biz_tag / doc_code 体现，任意业务复用同一端点。
"""

from collections.abc import Sequence

from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.llm import build_chat_model
from app.core.security import get_current_user
from app.core.rag.vector_service import VectorStoreService


# 模块级单例：未配置 API Key 时为 None（端点走确定性降级）。
# 通用脚手架自带独立 LLM，不依赖任何具体业务状态机模块。
qa_llm = build_chat_model(temperature=0.1)

# AIKnowledgeBase：知识切片 ORM 模型。检索/问答经服务层访问，
# 显式导入留给本路由后续的知识管理端点使用。
from app.models.ai_schema import AIKnowledgeBase  # noqa: F401

knowledge_router = APIRouter(prefix="/knowledge", tags=["Universal-RAG"])

# 问答召回参数
ASK_TOP_K = 3
ASK_MIN_SIMILARITY = 0.3

# 固定中立文案
NO_RESULT_ANSWER = (
    "知识库中暂未检索到与该问题直接相关的规程依据，"
    "请核实问题或联系管理员确认。"
)
DEGRADED_ANSWER_HEADER = "依据规程要求，相关条款如下：\n"

# 通用问答系统提示（仅依据参考条目作答，强制标注出处，无依据则拒答）
QA_SYSTEM_PROMPT = (
    "你是一个严谨的知识问答助手。请严格且仅依据用户提供的【参考条目】回答问题，"
    "不得使用参考条目之外的信息或自行推断。回答中需标注所引用条目的出处编号与章节。"
    "若参考条目不足以回答问题，请明确说明现有资料中没有相关依据，不要编造。"
)


# ---------------------------------------------------------------------------
# 请求 / 响应模型（Pydantic v2）
# ---------------------------------------------------------------------------
class SearchRequest(BaseModel):
    """向量检索请求。"""

    query: str
    biz_tag: str | None = None
    doc_code: str | None = None
    top_k: int = 3
    min_similarity: float = 0.5


class SearchResultItem(BaseModel):
    """单条检索结果。"""

    doc_code: str
    biz_tag: str
    section_title: str | None
    content: str
    similarity: float


class AskRequest(BaseModel):
    """知识问答请求。"""

    query: str
    biz_tag: str | None = None
    doc_code: str | None = None


class AskResponse(BaseModel):
    """知识问答响应：答案 + 命中条目的结构化引文。"""

    question: str
    answer: str
    citations: list[SearchResultItem]


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _to_result_items(rows: Sequence[dict]) -> list[SearchResultItem]:
    """将检索服务返回的 dict 列表映射为强类型结果项。"""
    return [
        SearchResultItem(
            doc_code=row["doc_code"],
            biz_tag=row["biz_tag"],
            section_title=row["section_title"],
            content=row["content"],
            similarity=row["similarity"],
        )
        for row in rows
    ]


def _build_context(citations: Sequence[SearchResultItem]) -> str:
    """把命中条目组装为提供给模型的参考文本。"""
    blocks = []
    for index, item in enumerate(citations, start=1):
        blocks.append(
            f"[条目{index}] 出处：{item.doc_code}"
            f"{' / ' + item.section_title if item.section_title else ''}\n"
            f"内容：{item.content}"
        )
    return "\n\n".join(blocks)


def _build_degraded_answer(
    citations: Sequence[SearchResultItem],
) -> str:
    """大模型不可用 / 调用失败时的确定性带引文答复。"""
    lines = [DEGRADED_ANSWER_HEADER.rstrip()]
    for item in citations:
        source = (
            f"【{item.doc_code}"
            f"{(' / ' + item.section_title) if item.section_title else ''}】"
        )
        lines.append(f"{source}\n{item.content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------
@knowledge_router.post("/search", response_model=list[SearchResultItem])
async def search_knowledge(
    req: SearchRequest,
    _current_user: dict = Depends(get_current_user),
) -> list[SearchResultItem]:
    """多维精准向量检索（需登录）。"""
    rows = await VectorStoreService().search_advanced(
        query=req.query,
        biz_tag=req.biz_tag,
        doc_code=req.doc_code,
        top_k=req.top_k,
        min_similarity=req.min_similarity,
    )
    return _to_result_items(rows)


@knowledge_router.post("/ask", response_model=AskResponse)
async def ask_knowledge(
    req: AskRequest,
    _current_user: dict = Depends(get_current_user),
) -> AskResponse:
    """带条文引文出处的通用问答（需登录）。

    大模型可用时基于召回条目生成答案；未配置 / 调用异常时确定性降级，
    citations 始终完整回填。
    """
    rows = await VectorStoreService().search_advanced(
        query=req.query,
        biz_tag=req.biz_tag,
        doc_code=req.doc_code,
        top_k=ASK_TOP_K,
        min_similarity=ASK_MIN_SIMILARITY,
    )
    citations = _to_result_items(rows)

    if not citations:
        return AskResponse(
            question=req.query,
            answer=NO_RESULT_ANSWER,
            citations=[],
        )

    # 大模型可用：尝试基于参考条目生成；任何调用异常均降级，保证不卡死
    if qa_llm is not None:
        try:
            response = await qa_llm.ainvoke(
                [
                    SystemMessage(content=QA_SYSTEM_PROMPT),
                    HumanMessage(
                        content=(
                            f"问题：{req.query}\n\n"
                            f"参考条目：\n{_build_context(citations)}"
                        )
                    ),
                ]
            )
            answer = response.content if response.content else ""
            if answer.strip():
                return AskResponse(
                    question=req.query,
                    answer=answer,
                    citations=citations,
                )
        except Exception:  # noqa: BLE001 —— 超时/限流/解析异常统一走确定性降级
            pass

    return AskResponse(
        question=req.query,
        answer=_build_degraded_answer(citations),
        citations=citations,
    )
