# 项目级工程规范：电网检修作业调度与智能问答中枢 (power-dispatch-agent)

## 一、 项目背景与架构全景
- **系统属性**：电网重大停电检修合规研判、两票三制调度令签发协同中枢，并集成电力安规多轮对话智能问答（Chat/RAG）。
- **核心模式**：确定性状态机（LangGraph）托底 + 人机协同安全熔断（Human-in-the-Loop）+ 真实大模型安规分析 + 本地持久化检查点（Checkpointer）。
- **工程目录拓扑**：
  - 前端：`frontend/` (Vue 3 + TypeScript + Vite + Pinia + 组件组合式 API `<script setup lang="ts">`)
  - 后端：`backend/` (FastAPI + LangGraph StateGraph + SQLite/Postgres AsyncCheckpointer + Pydantic v2)
  - 核心状态图：`backend/app/agent/graph.py` (单例编译，无状态计算)
  - 业务模式定义：`backend/app/schemas/dispatch.py` (强类型数据模型)
  - 存储底座：本地 SQLite 异步检查点文件 `backend/power_dispatch.db`

---

## 二、 电力业务红线与状态机判定规约 (核心业务规则)
- **检修风险定级与熔断机制**：
  - **110kV、220kV、500kV 及以上**：高压/超高压电网重大检修，风险必须定级为 `HIGH`，必须触发 `interrupt_before=['dispatcher_approval']` 流程挂起，等待调度值班长人工核签。
  - **10kV 及以下**：常规低压检修，在安措完备前提下判定为 `LOW`，自动签发许可令。
- **状态流转与单号规范**：
  - 申报工单状态流转：`INIT` -> `WAITING_DISPATCHER_REVIEW` -> `PERMITTED` / `REJECTED`。
  - 调度令格式：`DISP_CMD_<YYYYMMDDHHMM>_<4位HEX大写>`（如 `DISP_CMD_202610291019_B089`）。
- **多轮对话与知识库（Chat / RAG 拓展规范）**：
  - 调度工单流程（`PlanState`）与对话问答（`ChatState`）在图内保持状态隔离或清晰子图划分。
  - 对话消息使用标准 `messages: Annotated[list, add_messages]`，问答涉及《电网安全工作规程》（变电部分/线路部分）时优先检索本地向量切片，严格依据条款作答并标注出处条文，严禁模型无依据脑补规程。

---

## 三、 安全底线、命令与操作拦截
- **严禁硬编码敏感信息**：绝对禁止在代码中硬编码任何 API Key、数据库连接串或 Token。模型厂商配置必须统一从 `backend/.env` 读取。
- **Git 忽略与资产保护**：确保 `.env`、`power_dispatch.db`、`node_modules/`、`__pycache__/`、向量索引目录（如 `chroma_db/`、`faiss_index/`）全部写入 `.gitignore`。
- **高危操作二次确认**：严禁自动执行 `rm -rf`、删除数据库文件、格式化目录等破坏性指令；任何用户手动新建的业务文件/代码，未经明确指示严禁删除。
- **测试环境隔离**：新模块单点测试必须在独立的临时测试文件运行，测试完毕及时提醒或清理，严禁侵入核心业务流程。

---

## 四、 后端开发规范 (Python & LangGraph)
- **全链路纯异步优先 (Async Only)**：
  - 后端接口与状态机交互必须全部采用异步接口：`ainvoke`、`astream_events(version="v2")`、`aget_state`、`aupdate_state`。
  - 严禁在异步事件循环中调用阻塞式同步方法（如 `graph.get_state()`），杜绝触发 `asyncio.InvalidStateError`。
- **大模型调用与降级兜底**：
  - 统一使用 `ChatOpenAI` 适配器（兼容主流厂商标准）。合规审核与意图路由节点强制使用低温（`temperature=0.0` 或 `0.1`）。
  - 大模型调用必须包裹 `try-except`。网络超时、限流或解析异常时，必须依据电压等级执行硬编码安全兜底，严禁导致整个服务崩溃或卡死。
- **断点恢复机制**：调度长恢复执行时，必须以申报单号 `plan_id` 作为 `thread_id`，先通过 `aupdate_state(..., as_node='dispatcher_approval')` 注入审核状态，再通过 `ainvoke(None, config=config)` 恢复下游节点。

---

## 五、 前端开发规范 (Vue 3 + TypeScript)
- **流式输出与协议规范 (Streaming First)**：
  - 面向用户的打字机输出统一采用 **SSE（Server-Sent Events / HTTP POST）** 协议。
  - **默认使用成熟事件流驱动库（如 `@microsoft/fetch-event-source`）**，利用其内置的事件分帧、TCP Buffer 拼接和自动重连能力。
  - 仅在用户明确声明“使用原生方案/零依赖”时，才可使用原生 `fetch` + `ReadableStream`，此时必须显式编写严谨的 `buffer` 切分拼接代码，严禁对跨 TCP 分包截断的字符直接执行 `JSON.parse`。
- **代码规范与类型安全**：
  - 全局开启严谨 TypeScript，禁用 `any`，为组件 Props、API 响应载荷、SSE 事件均定义严密接口（`interface` / `type`）。
  - 统一采用 `<script setup lang="ts">` 组合式语法。
  - 模块引用必须使用路径别名（`@/...`），禁止层级过深的相对路径引用。严禁硬编码魔法值，状态与枚举必须抽取为常量或 TS Enum。

---

## 六、 常用命令与运行上下文 (Windows PowerShell)
- **环境要求**：Conda 虚拟环境 `(power-agent)`，Node.js 18+。
- **启动后端服务**：
  ```powershell
  # 位于 backend/ 目录下
  conda activate power-agent
  uvicorn main:app --reload --port 8000