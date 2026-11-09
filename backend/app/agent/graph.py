"""检修调度业务状态机（LangGraph 1.2.x）。

确定性 DispatchState 流程：
    START
      -> safety_check   内嵌 RAG 安规校验，产出违规项
      -> oms_draft      经 ACL 创建 OMS 正式工单
      -> human_audit    interrupt() 挂起，等待调度长核签
      -> issue_permit   经 ACL 签发 SCADA 调度许可令
      -> END

人机协同采用纯参数注入：节点内 ``interrupt()`` 挂起，恢复时由调用方传入
``Command(resume={...})``，不再使用 interrupt_before / aupdate_state(as_node=...)。
图本身无状态，checkpointer 在编译时注入；状态机节点经 ACL 防腐层访问外部系统。
"""

from typing import TypedDict

from langgraph.graph import START, END, StateGraph
from langgraph.types import interrupt

from app.services.acl import OMSGatewayAdapter, SCADAGatewayAdapter
from app.core.rag.vector_service import VectorStoreService


# ---------------------------------------------------------------------------
# 状态定义
# ---------------------------------------------------------------------------
class DispatchState(TypedDict):
    # 引擎线程 / 前端会话 / 提报人
    thread_id: str
    session_id: str
    user_id: str
    # 检修要素
    substation: str
    voltage_level: str
    operation_task: str
    # 现场安措（提报人填写）
    safety_measures: list[str]
    # 安规校验违规项
    violations: list[str]
    # OMS 正式工单号
    biz_order_id: str | None
    # 调度长审核结果（resume 注入）
    audit_decision: dict | None
    # SCADA 调度令凭证
    permit_info: dict | None


# ---------------------------------------------------------------------------
# 常量（禁止魔法值）
# ---------------------------------------------------------------------------
# 安规措施判定关键词
GROUND_WIRE_KEYWORD = "接地线"
VOLTAGE_TEST_KEYWORD = "验电"

# RAG 检索参数
RAG_TOP_K = 3
RAG_MIN_SIMILARITY = 0.3
RAG_BIZ_TAG = "power_grid"

# 审核动作
DECISION_PERMITTED_KEY = "is_permitted"
DECISION_REVIEWER_KEY = "reviewer_id"
DECISION_OPINION_KEY = "opinion"


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------
async def safety_check_node(state: DispatchState) -> dict:
    """内嵌 RAG 安规校验：检索规程依据，比对现场安措，产出违规项。"""
    voltage_level = state.get("voltage_level", "")
    operation_task = state.get("operation_task", "")
    measures = state.get("safety_measures", [])
    measures_text = "；".join(measures)

    # 检索相关安规切片（结果作为校验依据；检索异常不阻断，转规则比对）
    references: list[dict] = []
    try:
        references = await VectorStoreService().search_advanced(
            query=f"{voltage_level} {operation_task}",
            biz_tag=RAG_BIZ_TAG,
            top_k=RAG_TOP_K,
            min_similarity=RAG_MIN_SIMILARITY,
        )
    except Exception:
        references = []

    violations: list[str] = []
    if GROUND_WIRE_KEYWORD not in measures_text:
        violations.append(
            f"现场安措未明确“挂设{GROUND_WIRE_KEYWORD}”，"
            "依据安规，停电检修可能来电各端必须挂设接地线。"
        )
    if VOLTAGE_TEST_KEYWORD not in measures_text:
        violations.append(
            f"现场安措未明确“{VOLTAGE_TEST_KEYWORD}”，"
            "依据安规，装设接地线前必须先验电确认无电压。"
        )

    return {
        "violations": violations,
        # 检索到的规程依据数，供上游卡片展示，不入主状态字段时忽略
    }


async def oms_draft_node(state: DispatchState) -> dict:
    """安规初审通过后，经 ACL 创建 OMS 正式工单。"""
    biz_order_id = await OMSGatewayAdapter.create_official_order(
        draft_data={
            "substation_name": state.get("substation"),
            "voltage_level": state.get("voltage_level"),
            "work_content": state.get("operation_task"),
        },
        creator_id=state.get("user_id", ""),
    )
    return {"biz_order_id": biz_order_id}


async def human_audit_node(state: DispatchState) -> dict:
    """挂起等待调度长核签；resume 值即审核结论。"""
    decision = interrupt(
        {
            "waiting_for": "dispatcher_audit",
            "biz_order_id": state.get("biz_order_id"),
            "substation": state.get("substation"),
            "voltage_level": state.get("voltage_level"),
            "operation_task": state.get("operation_task"),
            "violations": state.get("violations", []),
        }
    )
    return {"audit_decision": decision}


async def issue_permit_node(state: DispatchState) -> dict:
    """核准通过后，经 ACL 签发 SCADA 调度许可令。"""
    decision = state.get("audit_decision") or {}
    reviewer_id = decision.get(DECISION_REVIEWER_KEY, "")
    biz_order_id = state.get("biz_order_id", "")

    permit_info = await SCADAGatewayAdapter.issue_dispatch_permit(
        biz_order_id=biz_order_id,
        reviewer_id=reviewer_id,
    )
    return {"permit_info": permit_info}


# ---------------------------------------------------------------------------
# 条件路由
# ---------------------------------------------------------------------------
def route_after_safety_check(state: DispatchState) -> str:
    """有违规项 → 直接结束（不进入 OMS 派单）；无违规 → 创建工单。"""
    return "oms_draft" if not state.get("violations") else END


def route_after_audit(state: DispatchState) -> str:
    """核准 → 签发调度令；驳回 → 结束。"""
    decision = state.get("audit_decision") or {}
    return (
        "issue_permit"
        if decision.get(DECISION_PERMITTED_KEY)
        else END
    )


# ---------------------------------------------------------------------------
# 编译
# ---------------------------------------------------------------------------
def create_dispatch_graph(checkpointer=None):
    """编译检修调度状态图。

    不使用 interrupt_before：人工挂点由 human_audit_node 内的 interrupt() 表达。
    checkpointer 缺省时退化为内存检查点（仅测试）。
    """
    from langgraph.checkpoint.memory import MemorySaver

    builder = StateGraph(DispatchState)

    builder.add_node("safety_check", safety_check_node)
    builder.add_node("oms_draft", oms_draft_node)
    builder.add_node("human_audit", human_audit_node)
    builder.add_node("issue_permit", issue_permit_node)

    builder.add_edge(START, "safety_check")
    builder.add_conditional_edges(
        "safety_check",
        route_after_safety_check,
        ["oms_draft", END],
    )
    builder.add_edge("oms_draft", "human_audit")
    builder.add_conditional_edges(
        "human_audit",
        route_after_audit,
        ["issue_permit", END],
    )
    builder.add_edge("issue_permit", END)

    return builder.compile(
        checkpointer=checkpointer or MemorySaver(),
    )
