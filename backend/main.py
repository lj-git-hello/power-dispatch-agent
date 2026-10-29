import os
import json
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.messages import HumanMessage

# 加载 .env 环境变量
load_dotenv()

from app.agent.graph import (
    create_dispatch_graph,
    RISK_DECISION_MARKER,
    INTENT_ROUTER_TAG,
)
from app.schemas.dispatch import (
    PlanApplyRequest,
    PermitRequest,
    AgentChatRequest,
    CardType,
    SSEEventType,
    PermitAction,
)

DB_PATH = "power_dispatch.db"
graph_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph_app
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph_app = create_dispatch_graph(checkpointer)
        print("⚡ [企业生产级中枢就绪] 双模状态机已挂载 + SQLite Checkpointer 启动")
        yield

app = FastAPI(title="智能电网检修调度协同中枢", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sse(event_type: SSEEventType, data: dict) -> str:
    """封装标准 A2UI SSE 事件帧：{'type': <枚举值>, 'data': {...}}"""
    payload = {"type": event_type.value, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ============================================================
# 双模智能体对话入口：安规多轮问答 + 业务申报审批（A2UI SSE）
# ============================================================
@app.post("/api/v1/chat/stream")
async def agent_chat_stream(req: AgentChatRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    action = (req.action_payload or {}).get("action")
    is_permit_action = action in (PermitAction.APPROVE.value, PermitAction.REJECT.value)

    async def event_generator():
        try:
            snapshot_before = await graph_app.aget_state(config)
            is_suspended = bool(snapshot_before) and "dispatcher_approval" in (snapshot_before.next or ())

            if is_permit_action:
                if not is_suspended:
                    # 防御性拦截：核准/驳回操作仅对挂起中的调度流程有效
                    yield _sse(SSEEventType.ERROR, {
                        "message": "当前会话不存在挂起待核准的调度流程，操作已被拦截。"
                    })
                    return
                yield _sse(SSEEventType.INTENT, {"intent": "DISPATCH_PERMIT"})
                human_text = req.message or (
                    "调度值班长核准开工申请。" if action == PermitAction.APPROVE.value
                    else "调度值班长驳回本次检修申请。"
                )
                # 企业断点恢复机制：先注入核准状态，再恢复下游节点执行
                await graph_app.aupdate_state(
                    config,
                    {
                        "is_permitted": action == PermitAction.APPROVE.value,
                        "intent": "DISPATCH_PERMIT",
                        "messages": [HumanMessage(content=human_text)],
                    },
                    as_node="dispatcher_approval",
                )
                # 恢复段无 LLM Token 流，仅驱动下游节点（issue_permit / 收尾）执行
                async for _ in graph_app.astream_events(None, config=config, version="v2"):
                    pass

            elif is_suspended:
                # 线程仍挂起等待调度长核准：拒绝普通对话输入驱动，防止污染挂起流程，
                # 由统一收口逻辑重发核准卡片等待操作
                pass

            else:
                initial_input = {"messages": [HumanMessage(content=req.message)]}
                async for event in graph_app.astream_events(initial_input, config=config, version="v2"):
                    if event["event"] != "on_chat_model_stream":
                        continue
                    # 过滤意图研判节点的结构化输出噪声流
                    if INTENT_ROUTER_TAG in (event.get("tags") or []):
                        continue
                    chunk = event["data"].get("chunk")
                    token = getattr(chunk, "content", "")
                    if not token:
                        continue
                    # 过滤协议尾部的结构化风险判定标记，保持对话流纯净
                    if RISK_DECISION_MARKER in token or "RISK:" in token:
                        continue
                    yield _sse(SSEEventType.TOKEN, {"content": token})

            # ---------- 统一收口：依据快照终态派发 A2UI 卡片与流程事件 ----------
            snapshot = await graph_app.aget_state(config)
            state = dict(snapshot.values) if snapshot else {}
            intent = state.get("intent")
            status = state.get("status")

            if not is_permit_action:
                yield _sse(SSEEventType.INTENT, {"intent": intent})

            if intent == "PLAN_APPLY":
                yield _sse(SSEEventType.CARD, {
                    "card_type": CardType.RISK_AUDIT.value,
                    "plan_id": state.get("plan_id"),
                    "substation_name": state.get("substation_name"),
                    "voltage_level": state.get("voltage_level"),
                    "work_content": state.get("work_content"),
                    "risk_level": state.get("risk_level"),
                    "audit_report": state.get("audit_report"),
                })

            if snapshot and "dispatcher_approval" in (snapshot.next or ()):
                yield _sse(SSEEventType.CARD, {
                    "card_type": CardType.APPROVAL.value,
                    "plan_id": state.get("plan_id"),
                    "risk_level": state.get("risk_level"),
                    "actions": [PermitAction.APPROVE.value, PermitAction.REJECT.value],
                })
                yield _sse(SSEEventType.WORKFLOW_INTERRUPT, {"waiting_for": "dispatcher_approval"})
            elif status == "REJECTED":
                yield _sse(SSEEventType.CARD, {
                    "card_type": CardType.REJECTED.value,
                    "plan_id": state.get("plan_id"),
                })
            elif status == "PERMITTED" and state.get("permit_no"):
                yield _sse(SSEEventType.CARD, {
                    "card_type": CardType.PERMIT.value,
                    "plan_id": state.get("plan_id"),
                    "permit_no": state.get("permit_no"),
                    "risk_level": state.get("risk_level"),
                })

            yield _sse(SSEEventType.DONE, {"status": status})
        except Exception as exc:
            # 全链路异常兜底：SSE 连接不中断，异常降级为标准 ERROR 事件
            yield _sse(SSEEventType.ERROR, {"message": f"智能体流式执行异常：{exc}"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/v1/dispatch/stream")
async def dispatch_stream(req: PlanApplyRequest):
    config = {"configurable": {"thread_id": req.plan_id}}
    initial_input = {
        "plan_id": req.plan_id,
        "substation_name": req.substation_name,
        "voltage_level": req.voltage_level,
        "work_content": req.work_content,
        "safety_measures": req.safety_measures,
        "status": "INIT"
    }

    async def event_generator():
        # 通过 astream_events(v2) 监听大模型真实 Token 流
        async for event in graph_app.astream_events(initial_input, config=config, version="v2"):
            # 捕获真实大模型吐出的每一个 Token
            if event["event"] == "on_chat_model_stream":
                if INTENT_ROUTER_TAG in (event.get("tags") or []):
                    continue
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    # 过滤掉协议尾部的结构化标记，保持控制台展示纯粹
                    if RISK_DECISION_MARKER not in chunk.content and "RISK:" not in chunk.content:
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content}, ensure_ascii=False)}\n\n"

        # 图执行暂停后，检测挂起状态
        snapshot = await graph_app.aget_state(config)
        if "dispatcher_approval" in snapshot.next:
            yield f"data: {json.dumps({'type': 'workflow_interrupt', 'waiting_for': 'dispatcher_approval'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/v1/dispatch/permit")
async def permit_plan(req: PermitRequest):
    config = {"configurable": {"thread_id": req.plan_id}}
    await graph_app.aupdate_state(config, {"is_permitted": req.permitted}, as_node="dispatcher_approval")
    final_state = await graph_app.ainvoke(None, config=config)
    return {"code": 200, "message": "许可令处理完成", "data": final_state}
