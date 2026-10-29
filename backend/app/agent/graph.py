import os
import asyncio
import uuid
import json
from datetime import datetime
from typing import TypedDict, Optional, Literal

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# 1. 状态定义
class PlanState(TypedDict):
    plan_id: str                      
    substation_name: str              
    voltage_level: str                
    work_content: str                 
    safety_measures: str              
    risk_level: Literal["LOW", "HIGH"]
    audit_report: str                 
    is_permitted: Optional[bool]      
    permit_no: Optional[str]          
    status: Literal["INIT", "WAITING_DISPATCHER_REVIEW", "PERMITTED", "REJECTED"]

# 2. 初始化大模型客户端（按企业规范读取环境变量）
llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL_NAME", "deepseek-chat"),
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1"),
    temperature=0.1,  # 规程研判类业务，采用低温确保事实准确性与严格遵守规程
    streaming=True    # 必须开启流式，支持下游事件监听
)

# 3. 真实企业级安规研判节点
async def safety_audit_node(state: PlanState):
    voltage = state.get("voltage_level", "10kV")
    substation = state.get("substation_name", "未知变电站")
    content = state.get("work_content", "")
    measures = state.get("safety_measures", "")

    # 企业级电力安规专用 System Prompt
    system_prompt = (
        "你是一名资深的国家电网电力调度安全合规专家。请根据《国家电网公司电力安全工作规程》对班组提交的停电检修计划进行合规性初审。\n\n"
        "【安规红线原则】：\n"
        "1. 若电压等级为 110kV、220kV、500kV，属于高压/超高压电网重大检修，必须判定为高风险【HIGH】，并明确指出必须由调度长校核潮流并下发调度许可令；\n"
        "2. 若电压等级为 10kV 及以下且不涉及高危负荷，可判定为常规低风险【LOW】；\n"
        "3. 输出格式要求：\n"
        "先用专业、规范的电力行业语言给出详细的安规分析说明；\n"
        "在回答的最末尾，严格使用如下格式标注最终风险结论：\n"
        "---RISK_DECISION---\n"
        "RISK: HIGH 或 LOW"
    )

    human_prompt = (
        f"检修计划申报明细：\n"
        f"- 目标变电站/线路：{substation}\n"
        f"- 电压等级：{voltage}\n"
        f"- 检修作业内容：{content}\n"
        f"- 现场安措及供电方案：{measures}\n\n"
        f"请进行安规研判："
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    try:
        # 异步调用大模型进行研判推理
        response = await llm.ainvoke(messages)
        full_content = response.content

        # 解析模型末尾的结构化判定
        if "RISK: HIGH" in full_content:
            risk = "HIGH"
            status = "WAITING_DISPATCHER_REVIEW"
        elif "RISK: LOW" in full_content:
            risk = "LOW"
            status = "PERMITTED"
        else:
            # 规则托底防幻觉：若模型未按格式输出，高压等级依然强制兜底熔断
            risk = "HIGH" if voltage in ["110kV", "220kV", "500kV"] else "LOW"
            status = "WAITING_DISPATCHER_REVIEW" if risk == "HIGH" else "PERMITTED"

        # 清理用于机器识别的分隔符，保证展示文本专业整洁
        clean_report = full_content.split("---RISK_DECISION---")[0].strip()

        return {
            "audit_report": clean_report,
            "risk_level": risk,
            "status": status,
            "is_permitted": True if risk == "LOW" else None
        }

    except Exception as e:
        # 企业级容错降级
        fallback_risk = "HIGH" if voltage in ["110kV", "220kV", "500kV"] else "LOW"
        fallback_report = f"【AI 服务熔断降级】安规大模型接口通信异常（{str(e)}），系统依据硬编码安规规则完成兜底裁决：风险定级为 [{fallback_risk}]。"
        return {
            "audit_report": fallback_report,
            "risk_level": fallback_risk,
            "status": "WAITING_DISPATCHER_REVIEW" if fallback_risk == "HIGH" else "PERMITTED"
        }

async def dispatcher_approval_node(state: PlanState):
    permitted = state.get("is_permitted", False)
    report = state.get("audit_report", "")
    
    if permitted:
        report += f"\n\n【调度长签发】调度值班长已完成电网潮流校核，确认安措完备，核准开工申请。"
        return {"audit_report": report, "status": "WAITING_DISPATCHER_REVIEW"}
    else:
        report += f"\n\n【调度长驳回】当前时段电网潮流过载，已驳回申请，指令班组延期重报。"
        return {"audit_report": report, "status": "REJECTED"}

async def issue_permit_node(state: PlanState):
    await asyncio.sleep(0.3)
    permit_no = f"DISP_CMD_{datetime.now().strftime('%Y%m%d%H%M')}_{uuid.uuid4().hex[:4].upper()}"
    report = state.get("audit_report", "") + f"\n【调度指令下达】正式调度许可令已签发，编号：{permit_no}。现场工作负责人可据此办理工作票许可手续。"
    
    return {
        "permit_no": permit_no,
        "status": "PERMITTED",
        "audit_report": report
    }

def risk_router(state: PlanState):
    return "dispatcher_approval" if state.get("risk_level") == "HIGH" else "issue_permit"

def approval_router(state: PlanState):
    return "issue_permit" if state.get("is_permitted") else END

def create_dispatch_graph(checkpointer=None):
    builder = StateGraph(PlanState)
    builder.add_node("safety_audit", safety_audit_node)
    builder.add_node("dispatcher_approval", dispatcher_approval_node)
    builder.add_node("issue_permit", issue_permit_node)

    builder.add_edge(START, "safety_audit")
    builder.add_conditional_edges("safety_audit", risk_router, ["dispatcher_approval", "issue_permit"])
    builder.add_conditional_edges("dispatcher_approval", approval_router, ["issue_permit", END])
    builder.add_edge("issue_permit", END)

    if checkpointer is None:
        checkpointer = MemorySaver()

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["dispatcher_approval"]
    )