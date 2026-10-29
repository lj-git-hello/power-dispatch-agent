import os
import json
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# 加载 .env 环境变量
load_dotenv()

from app.agent.graph import create_dispatch_graph
from app.schemas.dispatch import PlanApplyRequest, PermitRequest

DB_PATH = "power_dispatch.db"
graph_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph_app
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph_app = create_dispatch_graph(checkpointer)
        print("⚡ [企业生产级中枢就绪] 真实大模型已挂载 + SQLite Checkpointer 启动")
        yield

app = FastAPI(title="智能电网检修调度协同中枢", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    # 过滤掉协议尾部的结构化标记，保持控制台展示纯粹
                    if "---RISK_DECISION---" not in chunk.content and "RISK:" not in chunk.content:
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