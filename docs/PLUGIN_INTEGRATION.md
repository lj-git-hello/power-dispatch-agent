# 业务插件接入流水线（PLUGIN_INTEGRATION）

> **一句话目标**：接入一个新业务域 = 新增一个插件目录；`backend/main.py`、前端 `main.ts`、
> `frontend/src/core/**`、`backend/app/core/**` **零改动**。
>
> 本文档是本项目沉淀的方法论手册，也是新业务接入的唯一施工图。

---

## 〇、总览：物理隔离的三条铁律

| # | 铁律 | 机器可验证方式 |
|---|------|----------------|
| 1 | 通用层不得出现任何垂直业务词汇（角色名、单据类型、卡片类型、电压等级…） | `python backend/scripts/check_plugin_isolation.py` 零命中 |
| 2 | 通用层的依赖链不得触及任何业务模块 | `python -c "import app.core.security, sys; assert 'app.plugins' not in sys.modules"` |
| 3 | 业务资产只存在于插件目录内（代码、适配器、知识库原文） | `backend/app/plugins/<biz>/**` 之外无业务实现 |

> 底座只认**契约**（Protocol / 数据类），不认业务语义。所有"这单据叫什么""这角色干什么"
> 的解释权归插件。

---

## 一、五步接入流水线

```
第 0 步  梳理业务属性树      → 明确领域对象、状态、角色、风险分级
第 1 步  明确熔断点          → 哪些状态必须人工核签？挂在哪里？
第 2 步  定位 CAS 并发点      → 哪个状态会被多人同时操作？
第 3 步  定位消息表与留痕点   → 哪个线程产生哪些卡片与消息？
第 4 步  配置知识库与扩展表   → pgvector 知识库 / N 类扩展表 / 双连接池
──────────────────────────────────────────────────────────────
落地：  backend/app/plugins/<biz>/**   +   frontend/src/plugins/<biz>/**
```

### 第 0 步 · 梳理业务属性树

先画清楚"这个业务到底有哪些维度"，否则后面全是返工。标准产物：

| 维度 | 说明 | 落地位置 |
|------|------|----------|
| 领域对象 | 单据 / 工单 / 任务（本项目：检修作业计划） | 插件 `schemas.py` |
| 状态机 | 状态集合 + 合法迁移 | 插件 `states.py` + `graph.py` |
| 角色 | 谁可以提报 / 谁可以审批（角色字符串由插件自定义） | 插件 `constants.py` |
| 风险分级 | 触发熔断的判定规则（如"高压必熔断"） | 插件节点内纯函数 |
| 对话能力 | 是否接入自然语言问答（RAG / 业务问答） | 插件 `chat.py` |

**判定原则**：以上任何一项如果"通用层需要知道"，说明设计错了 —— 应该下沉到插件。

### 第 1 步 · 明确熔断点（Human-in-the-Loop）

- 底座已提供 `HITLController.resume_with_cas(...)`，插件**不要自己写**审批逻辑。
- 熔断点用 LangGraph 的 `interrupt()` 表达（节点内挂起），或 `interrupt_before`；
  二选一，插件内保持一致即可（**推荐节点内 `interrupt()`**：可以在挂起前完成风险定级，
  把结论随卡片一起交给审批人）。
- 挂起后**必须**满足：
  - 状态机上下文已持久化（Checkpointer），进程重启后可恢复；
  - 等待期间有明确的"待办"可查询（`HITLController.get_pending_tasks(role)`）；
  - 恢复时携带 `lock_version`（见第 2 步）。

**红线**：高危操作（资金流转、不可逆数据变更、高压电网操作）**不允许**全自动放行。
插件必须显式声明熔断点，且降级路径不得绕过熔断。

### 第 2 步 · 定位 CAS 并发点

只要一个状态可能被**两人同时**操作，就必须是 CAS（乐观锁）：

```
DB 层：ai_thread_mappings.lock_version
流程层：读取 lock_version → 决策 → 以 lock_version 作为 CAS 条件更新
失败方：HTTP 409（前端 useWorkflowAction 已按 409 提示"已被他人处理"）
```

插件接入要点：
1. CAS 条件写在**通用层封装的持久化方法**里，不要散落在 Router 的裸 SQL 中；
2. 幂等键（`idempotency_key`）用于"重复提交同一请求"的去重，与 CAS 解决的是不同问题：
   - 幂等键 → 防**重复提交**（网络重试）
   - CAS → 防**并发抢占**（两个审批人同时点）
3. 恢复执行用 `Command(resume=...)`，恢复后仍以 `lock_version` 为准再次校验。

### 第 3 步 · 定位消息表与留痕点

| 数据 | 写入者 | 通用能力 |
|------|--------|----------|
| 线程建档 | 插件 Router | `ThreadMappingStore.create_mapping(...)` |
| 卡片快照 / 文本消息 | 插件节点或 Router | `MessageRecorder.record_card / record_text` |
| 节点级 Token / 成本 / 时延留痕 | 插件通过 `ChatContext.trace_sink` 上报 | `TraceWriter`（通用层实现落库） |

- 卡片消息必须存**自包含重试载荷**（`retry_payload`）：前端脱离原会话也能重放该操作。
- 聊天线程与业务线程**必须命名空间隔离**（通用层已强制 `chat_` 前缀），否则对话消息会挂到
  业务工单线程下，CAS 恢复时会唤醒错误的图。

### 第 4 步 · 配置知识库与扩展表

- **知识库**：向量表 `ai_knowledge_base`（pgvector，HNSW 余弦索引）。
  - 维度硬限制：pgvector ANN 索引 **≤ 2000 维**；本项目固定 **1024 维**
    （`EMBEDDING_DIM=1024`，Matryoshka 显式降维）。
  - 原文文件**不放在 `app/` 内**：放在 `backend/plugins/<biz>/documents/`，用
    `python backend/scripts/rag_ingest_all.py --dir <路径> --biz_tag <标签>` 入库。
  - 批量大小固定 **8**：实测 `>=16` 时厂商返回的向量落入不同表示空间，入库与查询空间不一致
    会导致检索全失效。
  - **降级兜底**：外部向量服务不可用（超时 / 限流 / 返回空数据）时，`EmbeddingService`
    自动降级为 MD5 伪向量，保证入库链路不中断；但伪向量**无语义**，检索断言不可用。
- **N 类扩展表**：当前 N=1（知识库）。需要更多时按同样原则新增 `ai_*` 表
  （通用层拥有，插件只写数据）。
- **双连接池**：
  | 连接池 | 用途 | 生命周期 |
  |--------|------|----------|
  | LangGraph Checkpointer（psycopg） | 状态机检查点 | `checkpointer_manager` |
  | 业务引擎（SQLAlchemy + asyncpg） | 业务/AI 数据 | `async_engine` |
  两者**必须分开**：检查点写入是高频小事务，与业务查询混池会互相拖累。

---

## 二、落地清单（照着抄）

### 2.1 后端：新建 `backend/app/plugins/<biz>/`

```
app/plugins/<biz>/
├── __init__.py
├── constants.py      # 插件名 / 版本 / 角色 / 端点路径 / 状态图名（禁魔法值）
├── states.py         # 本业务状态机 State（继承 BaseWorkflowState）
├── schemas.py        # 本业务请求/响应模型（Pydantic v2）
├── graph.py          # build_dispatch_graph(checkpointer) -> 编译后的图
├── router.py         # APIRouter：apply / tasks / messages / audit
├── chat.py           # chat_handler（可选）：产出扁平 A2UI 事件
├── adapters/         # 外部系统防腐层实现（OMS / SCADA 之类）
└── plugin.py         # PLUGIN 清单（本插件的"身份证"）
```

`plugin.py` 是唯一入口，模板：

```python
"""XXX 业务插件清单（垂直插件入口）。"""

from app.core.plugin.manifest import PluginIdentity, PluginManifest
from app.plugins.<biz>.constants import (...)
from app.plugins.<biz>.graph import build_xxx_graph
from app.plugins.<biz>.router import xxx_router

PLUGIN = PluginManifest(
    name=XXX_PLUGIN_NAME,                    # 须等于目录名
    version=XXX_PLUGIN_VERSION,              # 须与前端一致
    router=xxx_router,
    router_prefix=XXX_ROUTER_PREFIX,         # 必须以 /api 开头
    graph_factory=build_xxx_graph,           # 纯问答型插件可缺省
    graph_name=XXX_GRAPH_NAME,               # 声明了 graph_factory 就必须给
    chat_handler=xxx_chat_handler,           # 未接入对话可缺省
    endpoint_paths={                         # 相对 router_prefix
        "tasks": XXX_ENDPOINT_TASKS,
        "messages": XXX_ENDPOINT_MESSAGES,
        "resume": XXX_ENDPOINT_RESUME,
        "apply": XXX_ENDPOINT_APPLY,
    },
    identities=(                             # 演示身份（外壳身份切换器的数据源）
        PluginIdentity(user_id="...", name="...", role="...", dept="..."),
    ),
)
```

**生效选择**（确定性优先，绝不隐式猜测）：

```bash
# backend/.env
ACTIVE_PLUGIN=<biz>        # 不设置时：只有一个插件则自动生效；多个则启动即报错并列出候选
```

**端点路径的单一真相源在后端**：manifest 下发的路径一律**相对 `/api`**
（如 `/v1/power-dispatch/tasks`），前端 axios `baseURL='/api'` 直接拼接，
杜绝前后端各写一份路径导致的漂移。

### 2.2 前端：新建 `frontend/src/plugins/<biz>/`

```
src/plugins/<biz>/
├── plugin.ts          # 插件清单（import.meta.glob 自动装载，main.ts 零改动）
├── cards/             # 卡片组件（按后端下发的 card_type 注册）
└── forms/             # 业务表单组件（由 App.vue 的 #business-form 插槽动态渲染）
```

`plugin.ts` 模板：

```ts
import type { WorkflowEndpoints } from '@/core/a2ui/types'
import type { PluginDefinition, PluginIdentity } from '@/core/plugins/registry'

export const XXX_PLUGIN_NAME = '<biz>'
export const XXX_PLUGIN_VERSION = '1.0.0'

export const XXX_ENDPOINTS: WorkflowEndpoints = {
  tasks: '/v1/<biz>/tasks',
  messages: '/v1/<biz>/messages',
  resume: '/v1/<biz>/audit',
  apply: '/v1/<biz>/apply',
}

export const XXX_IDENTITIES: PluginIdentity[] = [
  { id: '...', label: '...', role: '...' },
]

export const plugin: PluginDefinition = {
  name: XXX_PLUGIN_NAME,
  version: XXX_PLUGIN_VERSION,
  endpoints: XXX_ENDPOINTS,
  cards: { <后端实际下发的 card_type>: XxxCard },
  formComponent: XxxForm,
  identities: XXX_IDENTITIES,
}

export default plugin
```

装载由 Vite 的 `import.meta.glob('./plugins/*/plugin.ts', { eager: true })` 在**编译期**静态展开，
新增目录即被识别，`main.ts` 无需修改。

**卡片注册表是开放的**：前端只注册自己认识（或未知兜底渲染）的卡片；未注册的卡片由
`MessageCardHost` 以 JSON 兜底渲染，**绝不会白屏**。

### 2.3 通用外壳的动态装配

| 通用部件 | 插件如何参与 |
|----------|--------------|
| 路由挂载 | `manifest.router` + `manifest.router_prefix`（`main.py` 按清单挂载） |
| 状态机注册 | `manifest.graph_factory` + `manifest.graph_name`（`GraphRegistry` 按名注册） |
| 对话网关 | `manifest.chat_handler`（未提供 → 明确 error 事件，**不 500**） |
| 端点下发 | `manifest.endpoint_paths` → `GET /api/v1/plugin/manifest` |
| 身份切换器 | `manifest.identities` → Mock IAM 账号目录 + 前端身份下拉 |
| 表单渲染 | 前端 `PluginRegistry.getActive().formComponent` → `App.vue` 的 `#business-form` 插槽 |

---

## 三、通用层已内置的资产（插件直接用，别重写）

| 能力 | 模块 | 关键 API |
|------|------|----------|
| 状态机基类 | `app/core/workflow/base_state.py` | `BaseWorkflowState`（thread/session/user/status/error） |
| 状态图注册 | `app/core/workflow/graph_registry.py` | `GraphRegistry.register_graph / get_graph` |
| 人机协同 | `app/core/workflow/hitl.py` | `HITLController.resume_with_cas / get_pending_tasks / finalize_status` |
| 消息落库 | `app/core/workflow/message_recorder.py` | `record_card / record_text / list_by_thread` |
| 线程建档 | `app/core/workflow/thread_mapping_store.py` | `create_mapping / archive / get` |
| 防腐层契约 | `app/services/acl/protocols.py` | `IAMAdapterProtocol / OrderAdapterProtocol / CredentialAdapterProtocol` |
| 文档解析 | `app/core/rag/parsers/` | `iter_parse` 契约（pdf/docx/excel/text） |
| 语义切块 | `app/core/rag/chunking.py` | `RecursiveSemanticChunker`（MD5 内容指纹） |
| 向量服务 | `app/core/rag/vector_service.py` | `batch_upsert_chunks / search_advanced / soft_delete_document` |
| 向量降级 | `app/core/rag/embeddings.py` | `EmbeddingService`（异常 → MD5 伪向量） |
| LLM 工厂 | `app/core/llm.py` | `build_chat_model()`（无 Key 返回 `None` → 走确定性降级） |
| 插件机制 | `app/core/plugin/` | `PluginManifest / PluginLoader` |
| 对话网关 | `app/api/v1/agent.py` | `POST /api/v1/agent/chat-stream`（SSE） |
| 插件清单 | `app/api/v1/plugin.py` | `GET /api/v1/plugin/manifest` |

---

## 四、前后端契约速查

### 4.1 通用 A2UI SSE 事件（`POST /api/v1/agent/chat-stream`）

```
event: token    data: {"type":"token","content":"增量文本"}
event: ui_card  data: {"type":"ui_card","card_type":"xxx","data":{...}}
event: error    data: {"type":"error","message":"..."}
event: done     data: {"type":"done"}
```

- 事件类型定义在 `app/schemas/a2ui.py::A2UIEventType`，**通用层不得新增业务事件类型**。
- 插件只负责语义：实现 `chat_handler(context, request) -> AsyncIterator[AgentChatEvent]`。
- 网关负责：SSE 分帧、落库、留痕、错误收口（永远以 `done` 或 `error` 收口）。
- 前端消费：`@microsoft/fetch-event-source`（`frontend/src/core/api/agent.ts`），
  **禁止**直接对未完结 TCP chunk 做 `JSON.parse`。

### 4.2 插件 HTTP 端点约定

| 逻辑名 | 语义 | 幂等/并发 |
|--------|------|-----------|
| `apply` | 业务提报 | 建档幂等键 + 返回 `thread_id` |
| `tasks` | 待办列表 | 按角色过滤 |
| `messages` | 线程消息 | 只读 |
| `resume` | 恢复 / 审批 | **必须 CAS**（`lock_version`），冲突返回 409 |

### 4.3 审批请求体（插件自有 schema，字段名由插件定义）

底座不解释审批语义，插件自定字段（如电网插件用 `approved: bool`）；
唯一硬性要求：**必须携带 `thread_id` 与 `lock_version`**，否则 CAS 无法生效。

---

## 五、验收清单（接入完成后逐条打勾）

```bash
# 1. 隔离：通用层零业务词汇
python backend/scripts/check_plugin_isolation.py

# 2. 隔离：通用层依赖链不触达业务模块
cd backend && python -c "import app.core.security, sys; print('LEAKED:', [m for m in sys.modules if m.startswith('app.plugins')])"

# 3. 插件发现：无需改 main.py 即可生效
cd backend && python -c "from app.core.plugin.loader import PluginLoader; m=PluginLoader.load_active(); print(m.name, m.version, m.endpoints)"

# 4. 前后端版本偏斜：App.vue 启动时会自动比对并提示
# 5. 全量测试
cd backend && pytest tests -q
# 6. 前端类型检查 + 构建
cd frontend && npm run build
```

**换业务零改动验证（最硬的一条）**：

```bash
cp -r backend/app/plugins/<biz> backend/app/plugins/demo_biz   # 复制一份
# 修改 demo_biz/plugin.py 的 name / router_prefix / version
cd backend && python -c "from app.core.plugin.loader import PluginLoader; print(PluginLoader.load_active().name)"
# → demo_biz ；期间 main.py / App.vue / core/** 一行未改
rm -rf backend/app/plugins/demo_biz                             # 验证完清理
```

---

## 六、常见坑（都是踩过的）

| 坑 | 症状 | 正解 |
|----|------|------|
| `graph_name` 漏传 | 取图失败 / 静默唤醒别的业务的图 | 插件图**只**以插件名注册；不占用 `DEFAULT` 槽位 |
| CAS 条件写在裸 SQL 里 | 并发双核签 | CAS 收口在通用层持久化方法，Router 不写 SQL |
| 前后端各写一份端点路径 | 路径漂移，404 | 后端 manifest 为唯一真相源，前端启动时覆盖 |
| 聊天线程与业务线程同 id | 对话消息污染工单线程 | 通用层强制 `chat_` 前缀（已内置） |
| 卡片类型不一致 | 前端渲染成 JSON 兜底 | 以**后端实际下发**的 `card_type` 为准注册 |
| 向量批量 ≥ 16 | 检索全部失效（空间错乱） | 批量固定 8 |
| 向量维度 > 2000 | pgvector 建索引失败 | 1024 维（Matryoshka 降维） |
| 事件循环跨作用域复用连接 | `got Future attached to a different loop` | 连接池全局单例 → 事件循环也必须全局唯一（会话级） |
| Vue reactive 代理写入 IndexedDB | `DataCloneError` | 落库前 `toRaw` / `isReactive` 深剥离 |

---

## 七、目录速查

```
backend/
├── main.py                          # 通用容器（只装配，不含业务）
├── app/
│   ├── core/                        # ★ 通用底座：零业务词汇
│   │   ├── plugin/                  #   插件机制（manifest / loader）
│   │   ├── workflow/                #   状态机底座（HITL / CAS / 消息 / 建档）
│   │   ├── rag/                     #   通用 RAG（解析 / 切块 / 向量 / 检索）
│   │   ├── database.py              #   双连接池
│   │   ├── llm.py                   #   LLM 工厂
│   │   └── security.py              #   鉴权
│   ├── api/v1/                      # ★ 通用路由（agent / knowledge / plugin / auth）
│   ├── schemas/a2ui.py              # ★ 通用契约（A2UI 事件）
│   ├── services/acl/                # ★ 通用契约（IAM + 协议），不含业务实现
│   └── plugins/<biz>/               # ★ 业务插件（唯一可写业务的地方）
├── plugins/<biz>/documents/         # 业务知识库原文（不入 app/）
└── scripts/check_plugin_isolation.py  # 隔离门禁（CI 必跑）

frontend/src/
├── main.ts                          # 通用入口（import.meta.glob 自动装载插件）
├── App.vue                          # 通用外壳（动态渲染业务表单）
├── core/                            # ★ 通用底座：零业务词汇
│   ├── api/                         #   http / agent(SSE)
│   ├── plugins/registry.ts          #   插件注册表
│   ├── engine/                      #   存储 / 打字机 / 渲染
│   ├── workbench/                   #   工作台状态单例
│   └── views/                       #   通用视图（布局 / 待办 / 历史）
└── plugins/<biz>/                   # ★ 业务插件（卡片 / 表单 / 清单）
```
