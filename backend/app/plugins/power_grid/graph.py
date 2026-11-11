"""电网检修调度状态机（垂直插件）。

流程：
    START -> safety_check -> oms_draft -> human_audit(interrupt) -> issue_permit -> END

节点经通用服务层访问外部系统：RAG（安规检索）与 ACL（OMS/SCADA）。
图的编译/checkpointer 注入由 build_dispatch_graph 收口。
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.rag.vector_service import VectorStoreService
from app.plugins.power_grid.adapters import OMSGatewayAdapter, SCADAGatewayAdapter
from app.plugins.power_grid.constants import POWER_RAG_BIZ_TAG
from app.plugins.power_grid.states import DispatchState

# 安规措施判定关键词
GROUND_WIRE_KEYWORD = "接地线"
VOLTAGE_TEST_KEYWORD = "验电"

# RAG 检索参数
RAG_TOP_K = 3
RAG_MIN_SIMILARITY = 0.3
RAG_BIZ_TAG = POWER_RAG_BIZ_TAG

# 审核结论键
DECISION_PERMITTED_KEY = "is_permitted"
DECISION_REVIEWER_KEY = "reviewer_id"


async def safety_check_node(state: DispatchState) -> dict:
    """内嵌 RAG 安规校验：检索规程依据，比对现场安措，产出违规项。"""
    voltage_level = state.get("voltage_level", "")
    operation_task = state.get("operation_task", "")
    measures_text = "；".join(state.get("safety_measures", []))

    try:
        await VectorStoreService().search_advanced(
            query=f"{voltage_level} {operation_task}",
            biz_tag=RAG_BIZ_TAG,
            top_k=RAG_TOP_K,
            min_similarity=RAG_MIN_SIMILARITY,
        )
    except Exception:
        # 检索异常不阻断，转规则比对
        pass

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

    return {"violations": violations}


async def oms_draft_node(state: DispatchState) -> dict:
    """初审通过后经 ACL 创建 OMS 正式工单。"""
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
    """核准通过后经 ACL 签发 SCADA 调度许可令。"""
    decision = state.get("audit_decision") or {}
    permit_info = await SCADAGatewayAdapter.issue_credential(
        biz_order_id=state.get("biz_order_id", ""),
        reviewer_id=decision.get(DECISION_REVIEWER_KEY, ""),
    )
    return {"permit_info": permit_info}


def route_after_safety_check(state: DispatchState) -> str:
    """有违规 → 结束；无违规 → 创建工单。"""
    return "oms_draft" if not state.get("violations") else END


def route_after_audit(state: DispatchState) -> str:
    """核准 → 签发；驳回 → 结束。"""
    decision = state.get("audit_decision") or {}
    return (
        "issue_permit"
        if decision.get(DECISION_PERMITTED_KEY)
        else END
    )


def build_dispatch_graph(checkpointer=None):
    """编译电网检修调度图并返回。

    人工挂点由节点内 interrupt() 表达，不使用 interrupt_before。
    checkpointer 缺省退化为内存检查点（测试）。
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

    return builder.compile(checkpointer=checkpointer or MemorySaver())
