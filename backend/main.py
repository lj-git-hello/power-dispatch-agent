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
    A2UIEventType,
    A2UICardType,
    DispatcherDecision,
    DISPATCHER_DECISION_ALIASES,
)

DB_PATH = "power_dispatch.db"
graph_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph_app
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph_app = create_dispatch_graph(checkpointer)
        print("[企业生产级中枢就绪] 双模状态机已挂载 + SQLite Checkpointer 启动")
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


def _a2ui_sse(event_type: A2UIEventType, **fields) -> str:
    """封装 A2UI 聚合网关扁平事件帧：{'type': 'token'/'ui_card'/'error'/'done', ...其余字段平铺}"""
    payload = {"type": event_type.value, **fields}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _iter_graph_tokens(initial_input: dict, config: dict):
    """异步迭代状态机执行产生的 LLM Token 增量

    统一过滤：意图研判节点的结构化噪声流（Tag 识别）+ 安规协议尾部风险判定标记。
    严禁阻塞：全程基于 astream_events(version='v2') 异步事件驱动。
    """
    async for event in graph_app.astream_events(initial_input, config=config, version="v2"):
        if event["event"] != "on_chat_model_stream":
            continue
        # 过滤意图研判节点的结构化输出噪声流
        if INTENT_ROUTER_TAG in (event.get("tags") or []):
            continue
        chunk = event["data"].get("chunk")
        token = getattr(chunk, "content", "")
        if not token or not isinstance(token, str):
            continue
        # 过滤协议尾部的结构化风险判定标记，保持对话流纯净
        if RISK_DECISION_MARKER in token or "RISK:" in token:
            continue
        yield token


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
                update_values = {
                    "is_permitted": action == PermitAction.APPROVE.value,
                    "intent": "DISPATCH_PERMIT",
                    "messages": [HumanMessage(content=human_text)],
                }
                if action == PermitAction.REJECT.value:
                    # 修正缺陷：as_node 恢复会跳过节点体，驳回时必须显式落 REJECTED 状态
                    update_values["status"] = "REJECTED"
                await graph_app.aupdate_state(config, update_values, as_node="dispatcher_approval")
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


# ============================================================
# A2UI 流式聚合网关（第二阶段）：统一 Generative UI 事件出口
# ============================================================
@app.get("/api/v1/health")
async def health_check():
    """健康检查：网关存活与状态机挂载状态"""
    return {"code": 200, "status": "ok", "graph_ready": graph_app is not None}


@app.post("/api/v1/agent/chat-stream")
async def a2ui_agent_chat_stream(req: AgentChatRequest):
    """A2UI 双模聚合入口：常规对话/申报走 Token 流，卡片操作走断点恢复流"""
    config = {"configurable": {"thread_id": req.thread_id}}

    async def event_generator():
        try:
            payload = req.action_payload or {}
            decision_raw = payload.get("decision") or payload.get("action")
            opinion = str(payload.get("opinion") or payload.get("comment") or "").strip()

            # ---------- 分支 B：前端卡片交互唤醒驱动（调度长批准/驳回） ----------
            if decision_raw is not None:
                decision = DISPATCHER_DECISION_ALIASES.get(str(decision_raw).strip().lower())
                if decision is None:
                    yield _a2ui_sse(A2UIEventType.ERROR, message=f"无法识别的审核决定：{decision_raw}")
                    yield _a2ui_sse(A2UIEventType.DONE)
                    return

                snapshot_before = await graph_app.aget_state(config)
                if not snapshot_before or "dispatcher_approval" not in (snapshot_before.next or ()):
                    # 防御性拦截：核准/驳回操作仅对挂起中的调度流程有效
                    yield _a2ui_sse(A2UIEventType.ERROR, message="当前会话不存在挂起待核准的调度流程，操作已被拦截。")
                    yield _a2ui_sse(A2UIEventType.DONE)
                    return

                approved = decision == DispatcherDecision.APPROVED
                human_text = req.message or (
                    "调度值班长核准开工申请。" if approved else "调度值班长驳回本次检修申请。"
                )
                if opinion and not req.message:
                    human_text += f"审批意见：{opinion}"
                msg_count_before = len((snapshot_before.values or {}).get("messages") or [])

                # 企业断点恢复机制：注入审核决定（is_permitted/status 为状态机声明字段），再恢复下游节点。
                # 驳回时显式落 REJECTED——as_node 恢复会跳过 dispatcher_approval 节点体。
                await graph_app.aupdate_state(
                    config,
                    {
                        "is_permitted": approved,
                        "status": "WAITING_DISPATCHER_REVIEW" if approved else "REJECTED",
                        "intent": "DISPATCH_PERMIT",
                        "messages": [HumanMessage(content=human_text)],
                    },
                    as_node="dispatcher_approval",
                )
                # 恢复段无 LLM 调用，仅驱动下游节点（issue_permit / 收尾）执行
                async for _ in graph_app.astream_events(None, config=config, version="v2"):
                    pass

                snapshot = await graph_app.aget_state(config)
                state = dict(snapshot.values) if snapshot else {}
                # 推送恢复段节点生成的说明文本（issue_permit 的调度指令播报等）
                for msg in (state.get("messages") or [])[msg_count_before + 1:]:
                    content = getattr(msg, "content", "")
                    if getattr(msg, "type", "") == "ai" and isinstance(content, str) and content:
                        yield _a2ui_sse(A2UIEventType.TOKEN, content=content)

                # 推送许可凭证结果卡（签发 / 驳回统一出口）
                yield _a2ui_sse(
                    A2UIEventType.UI_CARD,
                    card_type=A2UICardType.PERMIT_RESULT.value,
                    data={
                        "plan_id": state.get("plan_id"),
                        "permit_no": state.get("permit_no"),
                        "status": state.get("status"),
                    },
                )
                yield _a2ui_sse(A2UIEventType.DONE)
                return

            # ---------- 分支 A：常规用户对话 / 申报指令 ----------
            if not (req.message or "").strip():
                yield _a2ui_sse(A2UIEventType.ERROR, message="message 与 action_payload 不能同时为空。")
                yield _a2ui_sse(A2UIEventType.DONE)
                return

            snapshot_before = await graph_app.aget_state(config)
            if snapshot_before and "dispatcher_approval" in (snapshot_before.next or ()):
                # 挂起保护：线程仍等待调度长核准，拒绝文本输入污染流程，重发核准卡片等待操作
                state_before = dict(snapshot_before.values)
                yield _a2ui_sse(
                    A2UIEventType.UI_CARD,
                    card_type=A2UICardType.APPROVAL_ACTION.value,
                    data={
                        "plan_id": state_before.get("plan_id"),
                        "voltage_level": state_before.get("voltage_level"),
                        "audit_report": state_before.get("audit_report"),
                        "risk_level": state_before.get("risk_level"),
                    },
                )
                yield _a2ui_sse(A2UIEventType.DONE)
                return

            async for token in _iter_graph_tokens(
                {"messages": [HumanMessage(content=req.message)]}, config
            ):
                yield _a2ui_sse(A2UIEventType.TOKEN, content=token)

            # 图流转完成，依据快照终态派发 A2UI 卡片
            snapshot = await graph_app.aget_state(config)
            state = dict(snapshot.values) if snapshot else {}
            if snapshot and "dispatcher_approval" in (snapshot.next or ()):
                # 命中 110kV+ 高压熔断挂起：下发调度审核卡片
                yield _a2ui_sse(
                    A2UIEventType.UI_CARD,
                    card_type=A2UICardType.APPROVAL_ACTION.value,
                    data={
                        "plan_id": state.get("plan_id"),
                        "voltage_level": state.get("voltage_level"),
                        "audit_report": state.get("audit_report"),
                        "risk_level": state.get("risk_level"),
                    },
                )
            elif state.get("status") == "PERMITTED" and state.get("permit_no"):
                # 10kV 及以下自动签发完成：下发电子凭证卡片
                yield _a2ui_sse(
                    A2UIEventType.UI_CARD,
                    card_type=A2UICardType.PERMIT_RESULT.value,
                    data={
                        "plan_id": state.get("plan_id"),
                        "permit_no": state.get("permit_no"),
                        "status": state.get("status"),
                    },
                )
            yield _a2ui_sse(A2UIEventType.DONE)

        except Exception as exc:
            # 全链路异常兜底：SSE 连接不中断，异常降级为标准 error 事件并保证终结信号
            yield _a2ui_sse(A2UIEventType.ERROR, message=f"智能体流式聚合网关执行异常：{exc}")
            yield _a2ui_sse(A2UIEventType.DONE)

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
    update_values = {"is_permitted": req.permitted}
    if not req.permitted:
        # 修正缺陷：as_node 恢复会跳过 dispatcher_approval 节点体，驳回时必须显式落 REJECTED 状态
        update_values["status"] = "REJECTED"
    await graph_app.aupdate_state(config, update_values, as_node="dispatcher_approval")
    final_state = await graph_app.ainvoke(None, config=config)
    return {"code": 200, "message": "许可令处理完成", "data": final_state}
