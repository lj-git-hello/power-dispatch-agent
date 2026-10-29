[用户交互端: Vue 3 + TS]
         ┌───────────────────────────────────┼───────────────────────────────────┐
         │ (左侧) 会话与历史单号列表            │ (右上) 消息流与动态 A2UI 卡片容器   │ (右下) 意图控制台
         └───────────────────────────────────┼───────────────────────────────────┘
                                             │ HTTP POST SSE (Streaming First)
                                             ▼
                                  [API 异步网关: FastAPI]
                                             │ 统一路由: /api/v1/agent/chat-stream
                                             ▼
                             [核心状态机引擎: LangGraph StateGraph]
                                             │
                                    ┌────────┴────────┐
                                    ▼                 ▼
                           [意图分类与提取路由]     [对话/RAG 问答分支]
                           (Intent & Slot Node)     (Safety QA & Vector Search)
                                    │
                                    ▼
                          [安规初审与研判节点]
                          (Safety Audit LLM Node)
                                    │
                         (高压/重大检修 110kV+)
                                    ▼
                 [人机协同中断挂起: interrupt_before] <─── 持久化快照 (AsyncSqliteSaver)
                                    │
                        (调度长人工核签事件注入)
                                    ▼
                           [调度令签发与结案]
                           (Issue Permit Node)