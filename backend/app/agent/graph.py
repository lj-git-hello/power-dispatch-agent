import os
import re
import uuid
import asyncio
from datetime import datetime
from typing import Annotated, Literal, Optional, TypedDict

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

# ---------------------------------------------------------------------------
# 常量定义（禁止魔法值）
# ---------------------------------------------------------------------------
RISK_DECISION_MARKER = "---RISK_DECISION---"  # 安规研判结构化判定分隔符
INTENT_ROUTER_TAG = "intent_router"           # 意图研判节点专属 Tag，供 SSE 网关过滤结构化噪声流
HIGH_RISK_KV_THRESHOLD = 110                  # 110kV 及以上判定为高压电网重大检修
MAX_HISTORY_MESSAGES = 12                     # 意图研判 / 安规问答携带的最大历史消息条数
# 提交渠道：仅遗留 REST 申报入口携带结构化业务字段直连，普通对话入口不允许短路
SUBMIT_CHANNEL_PLAN_FIELDS = "PLAN_FIELDS"
# 大模型调用超时（秒），均可被环境变量覆盖；意图研判与正文生成分别收口
ROUTER_TIMEOUT_SECONDS = float(os.getenv("LLM_ROUTER_TIMEOUT", "12"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT", "30"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))
# LLM 熔断降级后的关键词兜底规则
PLAN_APPLY_KEYWORDS = ("申报", "检修计划", "停电检修", "申请开工", "工作票")


# ---------------------------------------------------------------------------
# 1. 双模统一状态定义：安规多轮对话(Chat) + 检修申报审批(Plan) 共图共存
# ---------------------------------------------------------------------------
class GraphState(TypedDict):
    # —— 对话上下文（Chat 模式）——
    messages: Annotated[list, add_messages]                # 对话消息记录（多轮累积持久化）
    intent: Literal["QA", "PLAN_APPLY", "DISPATCH_PERMIT"]  # 意图路由结果
    # 提交渠道标记：仅结构化字段直连的遗留 REST 申报入口置位，用于区分确定性短路与普通对话
    submit_channel: Optional[str]

    # —— 申报工单业务字段（Plan 模式）——
    plan_id: str                        # 作业单号
    substation_name: str                # 变电站/线路名称
    voltage_level: str                 # 电压等级 (10kV / 110kV / 220kV / 500kV ...)
    work_content: str                  # 检修作业内容
    safety_measures: str               # 倒闸与接地线等安措预案
    risk_level: Literal["LOW", "HIGH"]  # 风险等级
    audit_report: str                  # AI 安规初审意见
    is_permitted: Optional[bool]        # 调度值班长是否签发许可
    permit_no: Optional[str]            # 调度许可令正式编号
    status: Literal["INIT", "WAITING_DISPATCHER_REVIEW", "PERMITTED", "REJECTED"]


# 向后兼容别名：既有代码以 PlanState 指代申报状态
PlanState = GraphState


# ---------------------------------------------------------------------------
# 2. 初始化大模型客户端（按企业规范从 backend/.env 读取，严禁硬编码密钥）
# ---------------------------------------------------------------------------
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.1,   # 规程研判类业务，采用低温确保事实准确性与严格遵守规程
    streaming=True,    # 支持 astream_events Token 监听
    timeout=LLM_TIMEOUT_SECONDS,  # 统一调用超时，杜绝长尾挂死
    max_retries=LLM_MAX_RETRIES,  # 内置失败重试
)


# ---------------------------------------------------------------------------
# 3. 意图研判：强类型结构化输出 Schema（分类 + 申报字段抽取一步完成）
# ---------------------------------------------------------------------------
class IntentDecision(BaseModel):
    """用户输入意图研判结果（QA / PLAN_APPLY 二分类 + 申报要素结构化抽取）"""
    intent: Literal["QA", "PLAN_APPLY"] = Field(
        description="意图分类：QA=电力安规咨询/规程条款问答；PLAN_APPLY=提报停电检修作业计划"
    )
    substation_name: Optional[str] = Field(
        None, description="目标变电站/线路名称，仅 PLAN_APPLY 时抽取"
    )
    voltage_level: Optional[str] = Field(
        None, description="电压等级（如 10kV/110kV/220kV/500kV），仅 PLAN_APPLY 时抽取"
    )
    work_content: Optional[str] = Field(
        None, description="检修作业内容，仅 PLAN_APPLY 时抽取"
    )
    safety_measures: Optional[str] = Field(
        None, description="现场安措预案，仅 PLAN_APPLY 时抽取"
    )


# 意图研判专用结构化模型：低温 + 强 Schema 约束，并打上专属 Tag 供 SSE 网关过滤其内部 Token 噪声
router_llm = llm.with_structured_output(IntentDecision).with_config(tags=[INTENT_ROUTER_TAG])

INTENT_SYSTEM_PROMPT = (
    "你是电网调度中枢的意图研判引擎。请严格研判用户最新输入属于以下哪类业务意图：\n"
    "1. QA：电力安规咨询、《电力安全工作规程》条款问答、倒闸操作/两票三制等技术概念解释；\n"
    "2. PLAN_APPLY：班组提报停电检修作业计划，通常包含目标变电站/线路、电压等级、检修作业内容、安措预案等申报要素。\n"
    "若判定为 PLAN_APPLY，必须同步从用户输入中抽取全部可识别的结构化申报字段；无法识别的字段置空，严禁臆造。"
)

SAFETY_QA_SYSTEM_PROMPT = (
    "你是国家电网资深电力安全专家，精通《国家电网公司电力安全工作规程》（变电部分/线路部分）、两票三制及倒闸操作规范。\n"
    "请严格依据安规规程条文回答用户问题，作答时标注出处条文编号；若问题超出安规依据范围，必须明确告知用户，"
    "严禁臆造规程条文。回答保持专业、精炼，使用规范的电力行业术语。"
)


# ---------------------------------------------------------------------------
# 4. 工具函数
# ---------------------------------------------------------------------------
def _generate_plan_id() -> str:
    """生成申报工单单号：PLAN_<YYYYMMDDHHMM>_<4位HEX大写>"""
    return f"PLAN_{datetime.now().strftime('%Y%m%d%H%M')}_{uuid.uuid4().hex[:4].upper()}"


def _fallback_risk(voltage: str) -> Literal["HIGH", "LOW"]:
    """硬编码安规兜底定级：110kV 及以上高危熔断；电压等级缺失时保守定级 HIGH"""
    if not voltage:
        return "HIGH"
    digits = re.findall(r"\d+", voltage)
    if not digits:
        return "HIGH"
    return "HIGH" if int(digits[0]) >= HIGH_RISK_KV_THRESHOLD else "LOW"


# ---------------------------------------------------------------------------
# 5. 节点逻辑
# ---------------------------------------------------------------------------
async def intent_router_node(state: GraphState):
    """意图路由节点：研判用户输入属于安规咨询(QA)还是提报检修作业(PLAN_APPLY)

    三级判定策略：结构化字段直连（确定性）-> LLM 低温研判（强 Schema）-> 关键词规则兜底（熔断降级）
    """
    # 1) 确定性直连：仅遗留 REST 申报入口（submit_channel=PLAN_FIELDS）携带结构化字段时短路，
    #    零 Token 消耗。普通对话入口即便检查点残留旧工单字段也不允许短路，避免污染新输入。
    if (
        state.get("submit_channel") == SUBMIT_CHANNEL_PLAN_FIELDS
        and state.get("voltage_level")
        and state.get("work_content")
    ):
        return {
            "intent": "PLAN_APPLY",
            "status": "INIT",
            "plan_id": state.get("plan_id") or _generate_plan_id(),
        }

    history = state.get("messages", [])[-MAX_HISTORY_MESSAGES:]
    last_user_text = ""
    for msg in reversed(history):
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            last_user_text = msg.content
            break

    # 2) LLM 低温研判（强类型 Schema 约束输出，严禁正则截取自然语言），超时强制兜底
    decision: Optional[IntentDecision] = None
    try:
        decision = await asyncio.wait_for(
            router_llm.ainvoke(
                [SystemMessage(content=INTENT_SYSTEM_PROMPT), *history]
            ),
            timeout=ROUTER_TIMEOUT_SECONDS,
        )
    except Exception:
        decision = None  # 超时 / 限流 / 异常：进入关键词规则兜底，严禁服务卡死

    if decision:
        intent = decision.intent
    else:
        intent = "PLAN_APPLY" if any(kw in last_user_text for kw in PLAN_APPLY_KEYWORDS) else "QA"

    if intent == "QA":
        return {"intent": "QA"}

    # 3) PLAN_APPLY：合并 LLM 抽取的申报字段（空值不覆盖既有上下文）
    update: dict = {"intent": "PLAN_APPLY", "status": "INIT"}
    if decision:
        if decision.substation_name:
            update["substation_name"] = decision.substation_name
        if decision.voltage_level:
            update["voltage_level"] = decision.voltage_level
        if decision.work_content:
            update["work_content"] = decision.work_content
        if decision.safety_measures:
            update["safety_measures"] = decision.safety_measures
    if not state.get("plan_id"):
        update["plan_id"] = _generate_plan_id()
    return update


async def safety_qa_node(state: GraphState):
    """安规问答节点：电力安规专家角色，基于多轮上下文以 astream 逐字流式解答"""
    history = state.get("messages", [])[-MAX_HISTORY_MESSAGES:]
    messages = [SystemMessage(content=SAFETY_QA_SYSTEM_PROMPT), *history]

    final_chunk = None
    try:
        # 显式 astream：逐 token 由外层 astream_events 实时转发，实现端到端打字机
        async for chunk in llm.astream(messages):
            final_chunk = chunk if final_chunk is None else final_chunk + chunk
    except Exception as exc:
        # 企业级容错降级：问答链路熔断不卡死，返回确定性提示
        return {
            "messages": [
                AIMessage(
                    content=f"【AI 服务熔断降级】安规专家服务暂时不可用（{exc}）。"
                    "请稍后重试，或直接查阅《电力安全工作规程》对应章节。"
                )
            ]
        }

    content = (getattr(final_chunk, "content", "") if final_chunk else "") or ""
    if not str(content).strip():
        content = "【AI 服务熔断降级】安规专家服务返回为空，请稍后重试。"
    return {"messages": [AIMessage(content=content)]}


async def safety_audit_node(state: GraphState):
    """安规初审节点：真实大模型合规研判，输出风险定级并驱动熔断/自动签发"""
    voltage = state.get("voltage_level", "")
    substation = state.get("substation_name") or "未知变电站"
    content = state.get("work_content", "")
    measures = state.get("safety_measures", "")

    # 企业级电力安规专用 System Prompt
    system_prompt = (
        "你是一名资深的国家电网电力调度安全合规专家。请根据《国家电网公司电力安全工作规程》对班组提交的停电检修计划进行合规性初审。\n\n"
        "【安规红线原则】：\n"
        "1. 若电压等级为 110kV、220kV、500kV 及以上，属于高压/超高压电网重大检修，必须判定为高风险【HIGH】，并明确指出必须由调度长校核潮流并下发调度许可令；\n"
        "2. 若电压等级为 10kV 及以下且不涉及高危负荷，可判定为常规低风险【LOW】；\n"
        "3. 输出格式要求：\n"
        "先用专业、规范的电力行业语言给出详细的安规分析说明；\n"
        "在回答的最末尾，严格使用如下格式标注最终风险结论：\n"
        f"{RISK_DECISION_MARKER}\n"
        "RISK: HIGH 或 LOW"
    )

    human_prompt = (
        f"检修计划申报明细：\n"
        f"- 目标变电站/线路：{substation}\n"
        f"- 电压等级：{voltage or '未知'}\n"
        f"- 检修作业内容：{content}\n"
        f"- 现场安措及供电方案：{measures}\n\n"
        f"请进行安规研判："
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    final_chunk = None
    try:
        # 显式 astream 逐字研判：正文 token 实时流出（RISK 标记由网关过滤），拿到全文后再结构化解析
        async for chunk in llm.astream(messages):
            final_chunk = chunk if final_chunk is None else final_chunk + chunk
        full_content = (getattr(final_chunk, "content", "") if final_chunk else "") or ""

        # 解析模型末尾的结构化判定
        if "RISK: HIGH" in full_content:
            risk, status = "HIGH", "WAITING_DISPATCHER_REVIEW"
        elif "RISK: LOW" in full_content:
            risk, status = "LOW", "PERMITTED"
        else:
            # 规则托底防幻觉：模型未按格式输出时，依据电压等级硬编码安全兜底
            risk = _fallback_risk(voltage)
            status = "WAITING_DISPATCHER_REVIEW" if risk == "HIGH" else "PERMITTED"

        # 清理用于机器识别的分隔符，保证展示文本专业整洁
        clean_report = full_content.split(RISK_DECISION_MARKER)[0].strip()

        return {
            "audit_report": clean_report,
            "risk_level": risk,
            "status": status,
            "is_permitted": True if risk == "LOW" else None,
            "messages": [AIMessage(content=clean_report)]
        }

    except Exception as exc:
        # 企业级容错降级
        fallback_risk = _fallback_risk(voltage)
        fallback_report = (
            f"【AI 服务熔断降级】安规大模型接口通信异常（{exc}），"
            f"系统依据硬编码安规规则完成兜底裁决：风险定级为 [{fallback_risk}]。"
        )
        return {
            "audit_report": fallback_report,
            "risk_level": fallback_risk,
            "status": "WAITING_DISPATCHER_REVIEW" if fallback_risk == "HIGH" else "PERMITTED",
            "is_permitted": True if fallback_risk == "LOW" else None,
            "messages": [AIMessage(content=fallback_report)]
        }


async def dispatcher_approval_node(state: GraphState):
    """调度值班长人工核准节点：读取注入的核准结论，落章审批意见"""
    permitted = state.get("is_permitted", False)
    report = state.get("audit_report", "")

    if permitted:
        decision_text = "【调度长签发】调度值班长已完成电网潮流校核，确认安措完备，核准开工申请。"
        return {
            "audit_report": report + f"\n\n{decision_text}",
            "status": "WAITING_DISPATCHER_REVIEW",
            "messages": [AIMessage(content=decision_text)]
        }
    else:
        decision_text = "【调度长驳回】当前时段电网潮流过载，已驳回申请，指令班组延期重报。"
        return {
            "audit_report": report + f"\n\n{decision_text}",
            "status": "REJECTED",
            "messages": [AIMessage(content=decision_text)]
        }


async def issue_permit_node(state: GraphState):
    """调度许可令签发节点：生成正式调度令编号"""
    await asyncio.sleep(0.3)  # 模拟调度指令网关下发耗时
    permit_no = f"DISP_CMD_{datetime.now().strftime('%Y%m%d%H%M')}_{uuid.uuid4().hex[:4].upper()}"
    decision_text = f"【调度指令下达】正式调度许可令已签发，编号：{permit_no}。现场工作负责人可据此办理工作票许可手续。"

    return {
        "permit_no": permit_no,
        "status": "PERMITTED",
        "audit_report": state.get("audit_report", "") + f"\n{decision_text}",
        "messages": [AIMessage(content=decision_text)]
    }


# ---------------------------------------------------------------------------
# 6. 条件路由
# ---------------------------------------------------------------------------
def intent_router_edge(state: GraphState) -> str:
    """意图条件路由：QA -> 安规问答；PLAN_APPLY -> 安规初审；DISPATCH_PERMIT -> 人工核准闸口"""
    intent = state.get("intent", "QA")
    if intent == "PLAN_APPLY":
        return "safety_audit"
    if intent == "DISPATCH_PERMIT":
        # 网关注入的调度核准意图：路由至人工熔断闸口。
        # interrupt_before 会在此再度挂起，等待 aupdate_state 注入核准结论后恢复，语义安全。
        return "dispatcher_approval"
    return "safety_qa"


def risk_router(state: GraphState):
    return "dispatcher_approval" if state.get("risk_level") == "HIGH" else "issue_permit"


def approval_router(state: GraphState):
    return "issue_permit" if state.get("is_permitted") else END


# ---------------------------------------------------------------------------
# 7. 组装双模状态图（单例编译，无状态计算，兼容 AsyncSqliteSaver 检查点持久化）
# ---------------------------------------------------------------------------
def create_dispatch_graph(checkpointer=None):
    """
    图拓扑：
        START -> intent_router -> (QA -> safety_qa -> END)
                                 |-> (PLAN_APPLY -> safety_audit -> 高危熔断/自动签发)
                                 |-> (DISPATCH_PERMIT -> dispatcher_approval)
    熔断红线：110kV 及以上重大检修必须 interrupt_before=['dispatcher_approval'] 挂起人工核签。
    """
    builder = StateGraph(GraphState)
    builder.add_node("intent_router", intent_router_node)
    builder.add_node("safety_qa", safety_qa_node)
    builder.add_node("safety_audit", safety_audit_node)
    builder.add_node("dispatcher_approval", dispatcher_approval_node)
    builder.add_node("issue_permit", issue_permit_node)

    builder.add_edge(START, "intent_router")
    builder.add_conditional_edges(
        "intent_router", intent_router_edge, ["safety_qa", "safety_audit", "dispatcher_approval"]
    )
    builder.add_edge("safety_qa", END)
    builder.add_conditional_edges("safety_audit", risk_router, ["dispatcher_approval", "issue_permit"])
    builder.add_conditional_edges("dispatcher_approval", approval_router, ["issue_permit", END])
    builder.add_edge("issue_permit", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["dispatcher_approval"]
    )
