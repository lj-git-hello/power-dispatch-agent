# 《系统设计说明书与手工测试验证指南》

> **项目**：`power-dispatch-agent` —— 电网检修作业调度与安规智能问答中枢
> **代码基线**：分支 `feat/postgres-checkpointer` · 提交 `b878941` · 生成日期 2026-11-12
> **文档定位**：与**当前工作区代码 100% 对应**的架构说明书 + 可照抄执行的端到端测试手册

---

## 关于本文档（请先读这一页）

### 本文档的两条铁律

1. **只描述当前真实存在的代码。** 文中出现的每一个文件路径、类名、函数签名、表名、列名、路由、SQL 片段，都来自对当前工作区源码的逐行核对。**不存在**的功能一律标注为「**未实现**」「**已废弃**」或「**蓝图描述，代码中不存在**」，绝不做「应该是这样」式的推测。
2. **本文档是只读调研产物。** 除本文件外，未修改任何业务代码、配置、迁移或测试脚本。

### 标注约定

| 标记 | 含义 |
|---|---|
| **【实测】** | 本次编写文档时**亲自运行过**并观察到的结果（容器状态、DB 行数、向量降级、pytest 收集行为等） |
| **【源码】** | 源码逐行核对得出的事实，未实际运行 |
| **【设计如此】** | 看起来像 bug，但代码逻辑上就是当前设计的既定行为（不是缺陷） |
| **【缺陷】** | 真实存在的问题或技术债，详见[第五章](#第五章现有代码存在的问题技术债与风险清单) |

### 与仓库中其他文档的关系

仓库中已有的以下文档**描述的是重构前的旧架构，与当前代码不符**，阅读时请以本文档为准：

| 文档 | 漂移点 |
|---|---|
| 根目录 `企业级通用 AI Agent 通用脚手架 · 落地开发与架构全景指南.md` | 描述了 `app/core/config.py`、`app/core/event_loop.py`、`app/core/workflow/bootstrap.py`、`app/core/workflow/resume.py`、`app/core/policy/protocols.py`、`app/core/acl/**`、`app/core/rag/chunker.py`、`app/core/rag/evaluation/` —— **这些文件在当前代码库中全部不存在** |
| 项目根 `CLAUDE.md` | 描述了 `backend/app/agent/graph.py`、`backend/app/schemas/dispatch.py`、`PlanState`、SQLite `backend/power_dispatch.db`、以及「110kV+ 必须定级 HIGH 并 `interrupt_before=['dispatcher_approval']`」的规则 —— **以上均已不存在或从未实现** |
| `project-docs/overall-structure.md` | 仍写 `AsyncSqliteSaver`，运行时早已切到 `AsyncPostgresSaver` |

### 读者路径建议

| 你的目的 | 建议阅读 |
|---|---|
| 我要接手维护这个项目 | 第一章 → 第二章 → 第五章 → 第六章 |
| 我要跑通一次完整验收 | 第四章（**从 4.0 读起**，那里声明了当前运行时基线） |
| 我要接入一个新的业务插件 | 第二章模块 6 + 第三章第 3 节 + 第六章 P2 |
| 我只想知道有哪些坑 | 第四章 4.4 踩坑对照表 + 第五章 |

---

## 目录

- [第一章 技术栈全景清单](#第一章技术栈全景清单)
- [第二章 通用底座核心功能模块详细设计](#第二章通用底座核心功能模块详细设计核心重点)
- [第三章 三大核心动线全链路穿透解析](#第三章三大核心动线全链路穿透解析)
- [第四章 手把手手动端到端测试验证指南](#第四章手把手手动端到端测试验证指南重中之重)
- [第五章 现有代码存在的问题、技术债与风险清单](#第五章现有代码存在的问题技术债与风险清单)
- [第六章 后续优化与功能扩展路线图](#第六章后续优化与功能扩展路线图)

---

# 第一章 技术栈全景清单

> 本章只列**在当前代码中真实被 import 并被调用**的组件。`backend/requirements.txt` 是 `pip freeze` 全量导出，其中包含若干**已不再被代码引用**的残留包，本章会明确标注。

## 1.1 后端核心框架

| 组件 | 版本 | 在本项目中的具体用途 | 代码引用位置 |
|---|---|---|---|
| FastAPI | 0.162.0 | HTTP 网关、依赖注入鉴权、`StreamingResponse` 承载 SSE | [`backend/main.py`](backend/main.py)、[`backend/app/api/v1/`](backend/app/api/v1/) |
| Starlette | 1.10.0 | FastAPI 底座；`StreamingResponse` / `CORSMiddleware` 实现 | 随 FastAPI 引入 |
| uvicorn | 0.54.0 | ASGI 服务器；Windows 上**必须带 `--reload`**（原因见 4.2） | 启动命令，见第四章 |
| Pydantic | 2.14.1 | v2 写法：请求/响应模型、`@model_validator`、`model_dump(mode="json", exclude_none=True)` | [`backend/app/schemas/a2ui.py`](backend/app/schemas/a2ui.py)、[`backend/app/api/v1/knowledge.py`](backend/app/api/v1/knowledge.py) |
| SQLAlchemy | 2.1.8 | 2.0 异步 ORM：`DeclarativeBase` + `Mapped`/`mapped_column`；同时用 `text()` 执行裸 SQL（CAS、待办池） | [`backend/app/models/ai_schema.py`](backend/app/models/ai_schema.py)、[`backend/app/core/workflow/hitl.py`](backend/app/core/workflow/hitl.py) |
| asyncpg | 0.32.0 | 业务池的异步 PG 驱动（`postgresql+asyncpg://`） | [`backend/app/core/database.py:31`](backend/app/core/database.py#L31) |
| Alembic | 1.20.1 | 迁移工具；线性两版（建表 → 1536→1024 改维重建 HNSW） | [`backend/migrations/`](backend/migrations/) |
| python-dotenv | 1.2.4 | 加载 `backend/.env`（**按绝对路径定位，不依赖 cwd**） | [`backend/main.py:29`](backend/main.py#L29)、[`backend/migrations/env.py`](backend/migrations/env.py) |
| httpx | 0.28.1 | **仅测试使用**：`ASGITransport` 在进程内驱动 FastAPI | [`backend/tests/test_dispatch_workflow.py`](backend/tests/test_dispatch_workflow.py) |
| pytest / pytest-asyncio | 9.2.0 / 1.4.1.post1 | 测试运行器；`asyncio_mode=strict`，异步用例须显式 `@pytest.mark.asyncio` | [`backend/pytest.ini`](backend/pytest.ini) |

**并发模型要点**：全链路异步（`async`/`await`、`AsyncSession`、`ainvoke`、`aget_state`），无阻塞式同步调用混入事件循环。

## 1.2 数据存储与向量引擎

| 组件 | 版本 | 具体用途 | 位置 |
|---|---|---|---|
| PostgreSQL | 16（镜像 `pgvector/pgvector:pg16`） | 唯一持久化存储：业务表 + 向量表 + LangGraph 检查点 | [`docker-compose.yml`](docker-compose.yml) |
| pgvector（服务端扩展） | 0.8.7 | `vector` 列类型 + HNSW ANN 索引 | `backend/scripts/init_db.sql`、迁移 `f36cb2d88733` |
| pgvector（Python 包） | 0.5.1 | SQLAlchemy `Vector(1024)` 类型映射 | [`backend/app/models/ai_schema.py:199`](backend/app/models/ai_schema.py#L199) |
| psycopg | 3.3.6 | LangGraph 检查点池的原生同步/异步驱动（`postgresql://`） | [`backend/app/core/database.py:33`](backend/app/core/database.py#L33) |
| psycopg-pool | 3.3.3 | `AsyncConnectionPool`，专供 checkpointer，**与业务池物理隔离** | [`backend/app/core/database.py:69-75`](backend/app/core/database.py#L69-L75) |
| langgraph-checkpoint-postgres | 3.2.0 | `AsyncPostgresSaver` —— 状态机检查点持久化 | [`backend/app/core/database.py:79`](backend/app/core/database.py#L79) |
| pypdf | 4.3.1 | PDF 解析 | [`backend/app/core/rag/parsers/pdf_parser.py`](backend/app/core/rag/parsers/pdf_parser.py) |
| python-docx | 1.1.2 | DOCX 解析 | [`backend/app/core/rag/parsers/docx_parser.py`](backend/app/core/rag/parsers/docx_parser.py) |
| openpyxl | 3.1.5 | XLSX / CSV 解析 | [`backend/app/core/rag/parsers/excel_parser.py`](backend/app/core/rag/parsers/excel_parser.py) |

**⚠️ 残留依赖**（在 `requirements.txt` 中但**当前代码未 import**）：`aiosqlite`、`langgraph-checkpoint-sqlite`、`sqlite-vec`、`httpx2`、`httpcore2`、`requests`、`requests-toolbelt`、`orjson`、`ormsgpack`、`zstandard`、`xxhash`、`uuid_utils`、`sniffio`、`annotated-doc` 等。其中 SQLite 三件套是插件化重构前的遗留（详见[第五章](#第五章现有代码存在的问题技术债与风险清单)）。

## 1.3 AI Agent 与 LLM 编排

| 组件 | 版本 | 具体用途 | 位置 |
|---|---|---|---|
| LangGraph | 1.2.18 | 确定性状态机：`StateGraph` + `add_conditional_edges` + 节点内 `interrupt()` | [`backend/app/plugins/power_grid/graph.py`](backend/app/plugins/power_grid/graph.py) |
| langgraph-checkpoint | 4.3.1 | `Command(resume=...)` 恢复语义 | [`backend/app/core/workflow/hitl.py:72`](backend/app/core/workflow/hitl.py#L72) |
| langchain-core | 1.7.0 | `HumanMessage` / `SystemMessage` 消息类型 | [`backend/app/api/v1/knowledge.py:18`](backend/app/api/v1/knowledge.py#L18) |
| langchain-openai | 1.7.3 | `ChatOpenAI` 适配器（兼容 OpenAI 标准协议的多家厂商） | [`backend/app/core/llm.py:13`](backend/app/core/llm.py#L13) |
| openai | 3.41.0 | `AsyncOpenAI` 原生 SDK —— **仅用于 embeddings**（聊天侧走 langchain） | [`backend/app/core/rag/embeddings.py:18`](backend/app/core/rag/embeddings.py#L18) |
| tenacity | 9.2.1 | 间接依赖（langchain 内置重试） | — |

**统一 LLM 工厂** [`backend/app/core/llm.py`](backend/app/core/llm.py)：

```python
def build_chat_model(
    *, temperature: float = DEFAULT_TEMPERATURE,   # 0.1
    model_name: str | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> ChatOpenAI | None:
    """构建 ChatOpenAI 实例；未配置 API Key 时返回 None。"""
```

- 环境变量：`OPENAI_API_KEY`（**缺失即返回 `None`，由调用方走确定性降级**）、`OPENAI_BASE_URL`、`OPENAI_MODEL_NAME`、`LLM_TIMEOUT`（默认 30.0）、`LLM_MAX_RETRIES`（默认 2）。
- 模型名回退：`DEFAULT_MODEL_NAME = "doubao-seed-2.1-lite"`。
- 合规研判与知识问答统一低温 `temperature ≤ 0.1`。

## 1.4 前端技术栈

| 组件 | 版本 | 具体用途 | 位置 |
|---|---|---|---|
| Vue | ^3.5.44 | 3.x 组合式 API（`<script setup lang="ts">`） | [`frontend/src/`](frontend/src/) |
| Vite | ^8.3.5 | 开发服务器 + 打包；`/api` 代理到 `127.0.0.1:8000`；`@` → `./src` 别名 | [`frontend/vite.config.ts`](frontend/vite.config.ts) |
| TypeScript | ~6.0.3 | 严格模式；`vue-tsc -b` 作为类型门禁 | [`frontend/package.json`](frontend/package.json) |
| **@microsoft/fetch-event-source** | ^2.0.1 | **SSE 消费库**：事件分帧、TCP Buffer 拼接、断网自动重连 | [`frontend/src/core/api/agent.ts`](frontend/src/core/api/agent.ts) |
| axios | ^1.21.0 | 通用 HTTP 实例（`baseURL='/api'`、30s 超时、Bearer 注入、错误归一化） | [`frontend/src/core/api/http.ts`](frontend/src/core/api/http.ts) |
| markdown-it + @vscode/markdown-it-katex + katex + highlight.js + dompurify | ^15.0.3 / ^1.1.2 / ^0.19.1 / ^11.12.0 / ^3.4.17 | Markdown + 公式 + 代码高亮 + XSS 净化 | [`frontend/src/core/utils/markdown.ts`](frontend/src/core/utils/markdown.ts) |
| localforage | ^1.10.0 | IndexedDB 持久化会话消息与会话集合 | [`frontend/src/core/engine/storage.ts`](frontend/src/core/engine/storage.ts) |
| lucide-vue-next | ^0.577.0 | 图标 | 前端视图 |
| qrcode.vue | ^3.11.0 | 调度许可令二维码（内容 = `permit_no|ca_signature_hash`） | [`frontend/src/plugins/power_grid/cards/PermitResultCard.vue`](frontend/src/plugins/power_grid/cards/PermitResultCard.vue) |
| tailwindcss + postcss + autoprefixer | ^3.4.19 / ^8.5.32 / ^10.6.2 | 原子化样式 | 样式层 |
| vue-tsc | ^3.3.13 | 类型检查（`npm run build` 的第一道工序） | [`frontend/package.json`](frontend/package.json) |

**⚠️ 关键缺失项**【源码】：

| 缺失 | 现状 | 影响 |
|---|---|---|
| `vue-router` | **未引入** | 无路由；页面切换靠 `App.vue` / `WorkbenchLayout.vue` 内部状态机 |
| `pinia` | **未引入** | 状态管理靠自建 `reactive()` 单例：[`frontend/src/core/workbench/useWorkbenchStore.ts:41`](frontend/src/core/workbench/useWorkbenchStore.ts#L41) |
| `vitest` / 任何测试框架 | **未引入**，`package.json` 无 `test` 脚本 | 前端**只能手工验证**；`npm run build` 是唯一自动化门禁 |

## 1.5 认证与并发安全机制

| 机制 | 实现 | 关键参数 | 位置 |
|---|---|---|---|
| JWT 签发/校验 | HS256，`sub`/`name`/`role`/`dept`/`iat`/`exp` | `ACCESS_TOKEN_EXPIRE_HOURS = 12`；密钥仅从 `JWT_SECRET_KEY` 读取，**缺失即 `RuntimeError`** | [`backend/app/services/acl/iam_adapter.py`](backend/app/services/acl/iam_adapter.py) |
| Bearer 提取 | `HTTPBearer(auto_error=True)` → 缺失即 401 | — | [`backend/app/core/security.py:16`](backend/app/core/security.py#L16) |
| 角色门禁 | `require_roles([...])` 依赖工厂 → 403 | — | [`backend/app/core/security.py:42-55`](backend/app/core/security.py#L42-L55) |
| CAS 乐观锁 | `lock_version` 列 + `UPDATE ... WHERE lock_version=:ver AND status='WAITING_HUMAN'`；`rowcount==0` → **409** | — | [`backend/app/core/workflow/hitl.py:41-68`](backend/app/core/workflow/hitl.py#L41-L68) |
| 双连接池隔离 | 业务池 `asyncpg`（`pool_size=10/max_overflow=20`）vs 检查点池 `psycopg`（`min_size=2/max_size=10/autocommit`） | — | [`backend/app/core/database.py`](backend/app/core/database.py) |
| CORS | `allow_origins=["*"]` + `allow_credentials=True` | 前端走 Vite 同源代理，实际不依赖 CORS | [`backend/main.py:76-82`](backend/main.py#L76-L82) |
| 人机协同熔断 | 状态图节点内 `interrupt()`（**不是** `interrupt_before`） | — | [`backend/app/plugins/power_grid/graph.py:79`](backend/app/plugins/power_grid/graph.py#L79) |

**⚠️ 不存在的安全能力**【源码】：全仓库**无任何密码哈希实现**（无 `bcrypt`/`passlib`/`pbkdf2`/`hash_password`）。登录是「凭 `user_id` 直接换 Token」的 Mock 模式 —— 这是刻意标注的演示态，不是可上生产形态（详见[第五章](#第五章现有代码存在的问题技术债与风险清单)）。

## 1.6 配置源清单

| 文件 | 作用 | 敏感项处理 |
|---|---|---|
| [`backend/.env`](backend/.env) | 后端运行时配置 | **已在 `.gitignore` 中**；本文档只出现键名 |
| [`docker-compose.yml`](docker-compose.yml) | PG 容器编排 | 口令用 `${DB_PASSWORD:?...}` 强制校验，**无硬编码** |
| [`backend/requirements.txt`](backend/requirements.txt) | 后端锁版依赖（`pip freeze` 导出，2026-11-06） | — |
| [`backend/requirements-dev.txt`](backend/requirements-dev.txt) | 开发期依赖 | — |
| [`frontend/package.json`](frontend/package.json) | 前端依赖与脚本 | — |
| [`backend/pytest.ini`](backend/pytest.ini) | pytest 路径、asyncio 模式与事件循环作用域 | — |
| [`backend/alembic.ini`](backend/alembic.ini) | 迁移配置（`script_location = %(here)s/migrations`） | — |

### `backend/.env` 键名清单【实测】

**当前实际存在的键**（只列键名，不含任何值）：

```
DB_HOST          DB_NAME          DB_PASSWORD      DB_PORT          DB_USER
EMBEDDING_DIM    EMBEDDING_MODEL_NAME               JWT_SECRET_KEY
OPENAI_API_KEY   OPENAI_BASE_URL OPENAI_MODEL_NAME
```

**代码会读但当前 `.env` 中缺失的键**（缺失即触发降级或默认值）：

| 键名 | 缺失后果 |
|---|---|
| `EMBEDDING_API_KEY` | 向量服务回落到 `OPENAI_API_KEY`（**供应商错配的根因**） |
| `EMBEDDING_BASE_URL` | 向量服务回落到 `OPENAI_BASE_URL`（同上） |
| `ACTIVE_PLUGIN` | 未设时若仅一个插件则自动选中；多插件则**启动即失败** |
| `LLM_TIMEOUT` | 回退默认 30.0 秒 |
| `LLM_MAX_RETRIES` | 回退默认 2 次 |

**代码会读、但已有默认值的键**：`DB_HOST`（`localhost`）、`DB_PORT`（`5432`）。

> 🔒 **本文档全篇只出现环境变量键名，不含任何真实凭据值。**

---

# 第二章 通用底座核心功能模块详细设计（核心重点）

> 本章拆解六个底座模块。每个模块按「**模块职责** → **核心源码文件路径** → **关键数据表结构** → **核心类/函数签名与内部实现逻辑**」四段式展开。
>
> **底座与业务的物理隔离原则**：所有位于 `backend/app/core/`、`backend/app/services/acl/`、`backend/app/schemas/`、`backend/app/api/v1/`（除业务插件目录）下的代码**不得出现任何电网业务词汇**。该约束由 CI 门禁 [`backend/scripts/check_plugin_isolation.py`](backend/scripts/check_plugin_isolation.py) 强制（24 词黑名单 + `@isolation-exempt` 豁免标记）。

## 2.1 多租户权限与 JWT 认证

### 模块职责

为所有受保护端点提供统一身份门禁：解析 Bearer Token → 校验签名与有效期 → 返回标准用户载荷（`sub`/`name`/`role`/`dept`）；并提供按角色放行的 RBAC 依赖工厂。底座**只维护「账号目录」**，不解释任何业务角色语义。

### 核心源码文件路径

| 文件 | 职责 |
|---|---|
| [`backend/app/core/security.py`](backend/app/core/security.py) | `get_current_user` / `require_roles` —— 通用门禁 |
| [`backend/app/services/acl/iam_adapter.py`](backend/app/services/acl/iam_adapter.py) | `IAMGatewayAdapter` —— 身份防腐适配器（Mock 实现） |
| [`backend/app/services/acl/protocols.py`](backend/app/services/acl/protocols.py) | `IAMAdapterProtocol` —— 适配器契约（PEP 544） |
| [`backend/app/api/v1/auth.py`](backend/app/api/v1/auth.py) | `POST /auth/login`、`GET /auth/me` |
| [`backend/app/core/plugin/loader.py:124-147`](backend/app/core/plugin/loader.py#L124-L147) | `PluginLoader._seed_identities` —— 把插件声明的演示身份登记进 IAM |

### 关键数据表结构

**本模块不直接写库** —— 身份信息全部编码进 JWT Claims，无独立用户表。

JWT Claims 结构【源码】：

| Claim | 类型 | 来源 | 说明 |
|---|---|---|---|
| `sub` | str | `MOCK_USERS[user_id]["user_id"]` | 账号 ID；`jwt.decode` 的 `require` 必填项 |
| `name` | str | 账号目录 | 展示名 |
| `role` | str | 账号目录 | 角色标识，**语义由插件解释** |
| `dept` | str | 账号目录 | 部门/班组，可为空串 |
| `iat` | datetime | 签发时刻 | UTC |
| `exp` | datetime | `iat + 12h` | UTC |

### 核心类与函数签名及内部实现逻辑

```python
# backend/app/services/acl/iam_adapter.py
JWT_SECRET_ENV = "JWT_SECRET_KEY"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12
ROLE_DEFAULT = "DEFAULT"

MOCK_USERS: dict[str, dict[str, str]] = {
    "demo_user": {"user_id": "demo_user", "name": "演示用户",
                  "role": ROLE_DEFAULT, "dept": ""},
}
```

```python
def _get_secret_key() -> str:
    """读取 JWT 签名密钥；缺失即 fail-fast，拒绝在无密钥下签发。"""
    secret = os.getenv(JWT_SECRET_ENV)
    if not secret:
        raise RuntimeError(
            f"环境变量 {JWT_SECRET_ENV} 未配置，无法签发 / 校验 JWT"
        )
    return secret
```

```python
class IAMGatewayAdapter:
    """统一身份认证网关防腐适配器（Mock 实现，无状态静态网关）。"""

    @staticmethod
    def register_user(user_id: str, name: str, role: str, dept: str = "") -> None:
        """登记演示账号（由插件装载器在启动时调用）。"""
        MOCK_USERS[user_id] = {"user_id": user_id, "name": name,
                               "role": role, "dept": dept}

    @staticmethod
    def create_access_token(user_id: str) -> str:
        """为预置账号下发 12 小时有效期的标准 JWT。未知 user_id 抛 KeyError。"""
        user = MOCK_USERS[user_id]          # ← 未知账号在此抛 KeyError
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user["user_id"], "name": user["name"],
            "role": user["role"], "dept": user["dept"],
            "iat": now, "exp": now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        }
        return jwt.encode(payload, _get_secret_key(), algorithm=JWT_ALGORITHM)

    @staticmethod
    def verify_token(token: str) -> dict[str, Any]:
        """解码并校验签名与有效期；过期抛 ExpiredSignatureError，非法抛 InvalidTokenError。"""
        return jwt.decode(token, _get_secret_key(), algorithms=[JWT_ALGORITHM],
                          options={"require": ["sub", "exp"]})
```

> 模块级向后兼容别名：`create_access_token = IAMGatewayAdapter.create_access_token`、`verify_access_token = IAMGatewayAdapter.verify_access_token`。

```python
# backend/app/core/security.py
security = HTTPBearer(auto_error=True)   # 缺失/格式错误 → FastAPI 自动 401

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """校验 Bearer Token 并返回标准用户载荷（sub/name/role/dept 等）。"""
    try:
        payload = IAMGatewayAdapter.verify_token(credentials.credentials)
    except ExpiredSignatureError:
        raise HTTPException(401, "Token 已过期，请重新登录。",
                            headers={"WWW-Authenticate": "Bearer"})
    except InvalidTokenError:
        raise HTTPException(401, "凭证无效，无法通过身份校验。",
                            headers={"WWW-Authenticate": "Bearer"})
    return payload

def require_roles(allowed_roles: list[str]):
    """角色门禁工厂：返回一个依赖，仅当用户角色在允许列表内时放行，否则 403。"""
    def _check_role(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(403, "权限不足，禁止访问该资源。")
        return current_user
    return _check_role
```

### 账号目录的实际内容【实测】

通用 IAM 预置 **1 个**账号（`demo_user`），业务演示身份由**插件**在启动时登记：

| user_id | name | role | dept | 来源 |
|---|---|---|---|---|
| `demo_user` | 演示用户 | `DEFAULT` | （空） | IAM 内置 `MOCK_USERS` |
| `applicant_01` | 张三 | `APPLICANT` | 运检一班 | `power_grid` 插件清单 `identities` |
| `dispatcher_lead` | 王调度长 | `DISPATCHER` | 调度控制中心 | `power_grid` 插件清单 `identities` |

> **设计要点**：底座**不预置任何业务角色名**。新增业务插件只需在自己的 `plugin.py` 里声明 `identities`，装载器自动登记 —— 换业务时底座零改动。

---

## 2.2 数据库双池隔离与并发乐观锁（CAS）

### 模块职责

1. 建立**两个物理隔离**的连接池：业务/向量池（asyncpg）与 LangGraph 检查点池（psycopg），避免长事务与 ANN 索引查询相互饿死；
2. 提供 CAS（Compare-And-Swap）乐观锁：并发审批时只有一个操作人能抢占同一挂起任务；
3. 提供「挂起 → 待办池 → 终态」三段式状态回写。

### 核心源码文件路径

| 文件 | 职责 |
|---|---|
| [`backend/app/core/database.py`](backend/app/core/database.py) | 引擎、会话工厂、双池管理器 |
| [`backend/app/core/workflow/hitl.py`](backend/app/core/workflow/hitl.py) | CAS 抢占 + 待办查询 + 终态回写 |
| [`backend/app/core/workflow/thread_mapping_store.py`](backend/app/core/workflow/thread_mapping_store.py) | 建档（幂等）/ 归档 / 待归档列举 |
| [`backend/app/models/ai_schema.py:35-97`](backend/app/models/ai_schema.py#L35-L97) | `AIThreadMapping` ORM 定义（含 `lock_version`） |

### 关键数据表结构

#### `ai_thread_mappings` —— 核心调度中枢表【源码】

| 列名 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `thread_id` | `String(64)` | **PK** | 引擎线程 ID（= Checkpointer 的 `thread_id`） |
| `session_id` | `String(64)` | `index=True`, NOT NULL | 前端 UI 会话 ID |
| `biz_order_id` | `String(64)` | `index=True`, NULL | **外部业务弱引用** —— ⚠️ 当前代码**从不写入**（见第五章） |
| `idempotency_key` | `String(64)` | **`unique=True`**, `index=True`, NULL | 幂等防护键；聊天线程固定为 `chat:<thread_id>` |
| `creator_id` | `String(64)` | `index=True`, NOT NULL | 发起人 |
| `creator_dept` | `String(64)` | NULL | 发起人部门（取自 JWT `dept`） |
| `creator_role` | `String(32)` | NOT NULL | 发起人角色 |
| `assigned_role` | `String(32)` | `index=True`, `server_default='APPLICANT'` | 受理角色；工单=`DISPATCHER`，聊天=`SYSTEM` |
| `status` | `String(32)` | `index=True`, `server_default='DRAFT'` | 见下方状态机 |
| `current_node` | `String(64)` | NULL | 状态机当前节点指针 —— ⚠️ **当前代码从不写入**（见第五章） |
| **`lock_version`** | `Integer` | `server_default=1`, `default=1`, NOT NULL | **CAS 乐观锁版本号** |
| `operator_id` | `String(64)` | NULL | 实际操作人（核签人） |
| `audit_opinion` | `Text` | NULL | 核签意见 |
| `signature_hash` | `String(128)` | NULL | 调度长核签签名摘要（`ca_signature_hash`） |
| `is_archived` | `Boolean` | `server_default=false`, `index=True`, NOT NULL | 软删除标记 |
| `archived_at` | `DateTime(tz)` | NULL | 归档时刻 |
| `created_at` | `DateTime(tz)` | `server_default=now()`, NOT NULL | |
| `updated_at` | `DateTime(tz)` | `server_default=now()`, `onupdate=now()`, NOT NULL | |

**状态取值**（实际出现在库中的）：

| status | 含义 | 产生位置 |
|---|---|---|
| `DRAFT` | 通用初态（`STATUS_DRAFT`） | `ThreadMappingStore.create_mapping` 默认 |
| `ACTIVE` | 无状态机的活跃对话线程（`STATUS_ACTIVE`） | `api/v1/agent.py` 建档 |
| `WAITING_HUMAN` | 挂起等待人工核签（`STATUS_WAITING_HUMAN`） | 工单提报 / 聊天外的通用挂起态 |
| `RUNNING` | CAS 抢占后的中间态（`HITLController.STATUS_RUNNING`） | `resume_with_cas` |
| `PERMITTED` / `REJECTED` | 业务终态 | 插件常量 |
| `SAFETY_REJECTED` | 安规否决终态（提报阶段即终止） | 插件常量 |

#### 索引与约束总览

- **唯一约束**：仅 `idempotency_key` 一个（`unique=True` + 独立 btree 索引）。
- **物理外键**：**0 个**。`ai_chat_messages.thread_id` 与 `ai_thread_mappings.thread_id` 仅**逻辑关联**（注释明示：为避免高并发会话清理时的外键校验与死锁）。
- **CAS 版本号**：见上表 `lock_version`。

### 核心类与函数签名及内部实现逻辑

#### 引擎与双池

```python
# backend/app/core/database.py
def _require_env(key: str) -> str:
    """读取必需的环境变量；缺失即 fail-fast。
    严禁为口令类变量提供兜底默认值。"""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"缺少必需的环境变量 {key}：请在 backend/.env 中配置后重启。")
    return value

DB_USER = _require_env("DB_USER")
DB_PASSWORD = _require_env("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = _require_env("DB_NAME")

ASYNC_DB_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
PSYCOPG_DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
```

> ⚠️ 这三个 `_require_env` 调用位于**模块 import 期**，因此 `backend/.env` 缺失或缺键 → **进程启动即 `RuntimeError`**（不是运行时报错）。

```python
async_engine = create_async_engine(
    ASYNC_DB_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=True,          # ⚠️ 生产会打印全量 SQL（含业务明文）
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)
```

```python
class CheckpointerManager:
    """管理 LangGraph 检查点连接池生命周期与表初始化"""

    def __init__(self, conn_string: str):
        self.conn_string = conn_string
        self.pool: AsyncConnectionPool | None = None
        self.saver: AsyncPostgresSaver | None = None

    async def init_pool(self):
        # 建立独立连接池，防止与业务大事务/向量索引查询产生死锁
        self.pool = AsyncConnectionPool(
            conninfo=self.conn_string,
            min_size=2, max_size=10, open=False,
            kwargs={"autocommit": True},
        )
        await self.pool.open()
        self.saver = AsyncPostgresSaver(self.pool)
        await self.saver.setup()      # 幂等建表：checkpoints / checkpoint_blobs / checkpoint_writes

    async def close_pool(self):
        if self.pool:
            await self.pool.close()

checkpointer_manager = CheckpointerManager(PSYCOPG_DB_URL)
```

> **双池隔离原理**：业务池走 asyncpg（SQLAlchemy 生态，`pool_size=10/max_overflow=20`），检查点池走 psycopg 原生池（`min_size=2/max_size=10` + `autocommit=True`）。即使业务事务长事务占满连接，状态机检查点仍有独立配额可用。`stress_pool_exhaustion.py` 就是专门验证这一点的压测脚本。

#### CAS 乐观锁

```python
# backend/app/core/workflow/hitl.py
class HITLController:
    """无状态 HITL 并发控制器（全部静态方法）。"""

    @staticmethod
    async def resume_with_cas(
        thread_id: str,
        lock_version: int,
        resume_payload: dict[str, Any],
        operator_id: str,
        audit_opinion: str | None = None,
        graph_name: str = DEFAULT_GRAPH_NAME,
    ) -> None:
        """CAS 抢占成功后，用 Command(resume) 唤醒对应工作流图。
        抢占失败（已被处理 / 版本失效）抛 409。"""
```

内部逻辑（三段）：

**① CAS UPDATE —— 抢占**

```sql
UPDATE ai_thread_mappings
SET status = :running,          -- 'RUNNING'
    lock_version = lock_version + 1,
    operator_id = :uid,
    audit_opinion = :opinion
WHERE thread_id = :tid
  AND lock_version = :ver        -- ← 版本必须精确匹配
  AND status = :waiting          -- ← 且必须仍处于挂起态
```

- `result.rowcount == 0` → `await session.rollback()` + `raise HTTPException(409, "任务已被其他操作人处理或版本已失效")`。
- 抢占成功 → `lock_version` 自增 1，`operator_id` / `audit_opinion` 落库。

**② 依赖反转取图**

```python
graph = GraphRegistry.get_graph(graph_name)
```

底座**不 import 任何业务图**；图由插件在装配阶段注册进 `GraphRegistry`（依赖反转）。

**③ Command 唤醒**

```python
await graph.ainvoke(
    Command(resume=resume_payload),
    config={"configurable": {"thread_id": thread_id}},
)
```

#### 待办池查询（归档过滤是必需的）

```python
@staticmethod
async def get_pending_tasks(assigned_role: str) -> list[dict[str, Any]]:
    """查询指定角色的待办记录（WAITING_HUMAN 且未归档）。"""
```

```sql
SELECT thread_id, session_id, creator_id, creator_dept,
       status, assigned_role, lock_version, audit_opinion, created_at
FROM ai_thread_mappings
WHERE status = 'WAITING_HUMAN'
  AND assigned_role = :role
  AND is_archived = false        -- ← 关键过滤
ORDER BY created_at
```

> 代码注释明确写出理由：**待办池是「只增不减」的工作队列，一旦缺少生命周期过滤，历史遗留的挂起记录会永久沉在审批人池里（无人核准即永不消失）。** 这是 `is_archived` 字段存在的全部意义。
>
> `created_at` 在返回前被转成 **ISO 8601 字符串**（保证可 JSON 序列化）。

#### 终态回写（**无 CAS 校验**）

```python
@staticmethod
async def finalize_status(thread_id: str, final_status: str,
                          signature_hash: str | None = None) -> None:
    """流程结束后回写映射终态；可选落签名哈希。"""
```

- `signature_hash is not None` → `UPDATE ... SET status=:status, signature_hash=:sig WHERE thread_id=:tid`
- 否则 → `UPDATE ... SET status=:status WHERE thread_id=:tid`
- **该 UPDATE 不带 `lock_version` 条件** —— 属于「抢占已成功、后续终态无条件落盘」的约定式写法（见第五章）。

#### 建档幂等

```python
# backend/app/core/workflow/thread_mapping_store.py
class ThreadMappingStore:
    """无状态线程映射仓储（全部静态方法）。"""

    @staticmethod
    async def create_mapping(
        thread_id: str, session_id: str, creator_id: str,
        creator_role: str, assigned_role: str,
        creator_dept: str | None = None,
        status: str = STATUS_DRAFT,
        idempotency_key: str | None = None,
    ) -> AIThreadMapping:
        """建立线程映射（幂等）：已存在则原样返回，不重复插入。"""
```

实现要点：

1. **读-before-write**：`await session.get(AIThreadMapping, thread_id)` 命中则直接返回原对象。
2. **唯一约束兜底**：`session.commit()` 抛 `IntegrityError` → `rollback()` → 重新 `get` → 命中则返回，否则**向上抛出**（不吞）。
3. `lock_version=1` 在创建时显式写入。
4. ⚠️ **参数列表中没有 `biz_order_id`** —— 这是第五章 G1 弱引用列恒为 NULL 的根因。

其他方法：`archive(thread_id) -> bool`（软删除）、`archive_many(thread_ids) -> list[str]`（`UPDATE ... WHERE thread_id = ANY(:ids) AND is_archived = false RETURNING thread_id`）、`list_pending(before=None) -> list[dict]`（供归档脚本）、`get(thread_id) -> dict | None`。

---

## 2.3 多格式流式文档解析与 RAG 向量检索

### 模块职责

把「多格式文件」变成「可检索的向量切片」：多格式流式解析 → 语义层级递归分块 → 批量 Embedding（带确定性伪向量降级）→ 分批幂等入库（pgvector + HNSW）；并提供带元数据预过滤的余弦 ANN 检索与软删除。

### 核心源码文件路径

| 文件 | 职责 |
|---|---|
| [`backend/app/core/rag/parsers/base.py`](backend/app/core/rag/parsers/base.py) | `ParsedDocument` 数据结构 + `BaseParser` 抽象基类 |
| [`backend/app/core/rag/parsers/factory.py`](backend/app/core/rag/parsers/factory.py) | 后缀 → 解析器路由 |
| [`backend/app/core/rag/parsers/{text,docx,pdf,excel}_parser.py`](backend/app/core/rag/parsers/) | 四类具体解析器 |
| [`backend/app/core/rag/chunking.py`](backend/app/core/rag/chunking.py) | `RecursiveSemanticChunker` + `DocumentChunk` |
| [`backend/app/core/rag/embeddings.py`](backend/app/core/rag/embeddings.py) | `EmbeddingService` + 伪向量降级 |
| [`backend/app/core/rag/vector_service.py`](backend/app/core/rag/vector_service.py) | `VectorStoreService` —— 入库 / 检索 / 软删除 |
| [`backend/app/models/ai_schema.py:168-211`](backend/app/models/ai_schema.py#L168-L211) | `AIKnowledgeBase` ORM（含 HNSW 索引） |
| [`backend/scripts/rag_ingest_file.py`](backend/scripts/rag_ingest_file.py) / [`rag_ingest_all.py`](backend/scripts/rag_ingest_all.py) | 入库 CLI |

### 关键数据表结构

#### `ai_knowledge_base` —— 向量知识库【源码】

| 列名 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `id` | `String(64)` | **PK**, 默认 `uuid4` | |
| `doc_code` | `String(64)` | `index=True`, NOT NULL | 规程编码（如 `DL-408-2021`、`SMOKE-TEST-001`） |
| `biz_tag` | `String(32)` | NOT NULL | 业务标签（如 `power_grid`）—— 检索时的元数据预过滤维度 |
| `section_title` | `String(128)` | NULL | 章节 / 页码标识 |
| `content` | `Text` | NOT NULL | 切片正文 |
| **`embedding`** | **`Vector(1024)`** | NOT NULL | **pgvector 1024 维余弦向量** |
| `is_active` | `Boolean` | `server_default=true`, NOT NULL | 软删除开关 |
| `doc_version` | `String(32)` | `server_default='v1.0'`, NOT NULL | 规程版本 |
| `created_at` | `DateTime(tz)` | `server_default=now()`, NOT NULL | |

**索引清单**：

| 索引名 | 类型 | 列 | 参数 | 用途 |
|---|---|---|---|---|
| `idx_knowledge_tag_active` | btree | `(biz_tag, is_active)` | — | 元数据预过滤（HNSW 查询的前置过滤列） |
| **`idx_knowledge_embedding_hnsw`** | **HNSW** | `embedding` | `m=16`, `ef_construction=64`, `vector_cosine_ops` | 余弦距离 ANN 索引 |
| `ix_ai_knowledge_base_doc_code` | btree | `doc_code` | — | 按文档码定位切片 |

**维度演进**（迁移链，线性两版）：

```
f36cb2d88733_init_ai_storage_3_plus_n   → 建 vector 扩展 + 4 张 ai_ 表，embedding VECTOR(1536)
844a9489b970_resize_embedding_to_1024    → DROP HNSW → ALTER 到 vector(1024) → 重建 HNSW
```

> 降维原因（ORM 注释原文）：底层 `doubao-embedding-vision` 原生输出 1536 维，经 Matryoshka 显式降维到 1024 维，以满足 pgvector ANN 索引 ≤2000 维的硬限制。

### 核心类与函数签名及内部实现逻辑

#### ① 解析器工厂

```python
# backend/app/core/rag/parsers/factory.py
class UnsupportedFileTypeError(Exception):
    """不支持的文件后缀时抛出。"""

_PARSER_REGISTRY: dict[str, type[BaseParser]] = {
    "txt": TextParser, "md": TextParser,
    "docx": DocxParser, "pdf": PdfParser,
    "xlsx": ExcelParser, "csv": ExcelParser,
}

class DocumentParserFactory:
    @staticmethod
    def get_parser(file_path: str) -> BaseParser: ...     # 未知后缀 → UnsupportedFileTypeError
    @staticmethod
    def iter_file(file_path: str) -> Iterator[ParsedDocument]: ...   # 流式（推荐）
    @staticmethod
    def parse_file(file_path: str) -> list[ParsedDocument]: ...      # 物化（小文件）
```

**支持的 6 种后缀**：`txt` / `md` / `docx` / `pdf` / `xlsx` / `csv`。

解析产物结构：

```python
class ParsedDocument(BaseModel):
    title: str          # 文件或章节名
    content: str        # 提取的纯文本
    source_path: str    # 物理路径
    doc_type: str       # 后缀（小写无点）
    metadata: dict = Field(default_factory=dict)   # 页码、块号、行列范围等
```

#### ② 语义分块器

```python
# backend/app/core/rag/chunking.py
SEMANTIC_SEPARATORS: list[str] = ["\n\n", "\n", "；", "。", "！", "？", ";", ". "]
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
```

```python
class DocumentChunk(BaseModel):
    doc_code: str
    biz_tag: str
    section_title: str
    content: str
    chunk_index: int
    content_hash: str = ""      # model_validator(mode="after") 自动填充

    @model_validator(mode="after")
    def _fill_content_hash(self) -> "DocumentChunk":
        if not self.content_hash:
            self.content_hash = hashlib.md5(
                f"{self.doc_code}:{self.content.strip()}".encode()
            ).hexdigest()
        return self
```

```python
class RecursiveSemanticChunker:
    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE,
                 chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> None:
        # 校验：chunk_size > 0；0 <= chunk_overlap < chunk_size，否则 ValueError
```

**切分算法三步**：

1. `_recursive_split(text, separators)` —— 在**层级分隔符**上递归：优先 `\n\n`（段落）→ `\n`（行）→ `；。！？`（中文句读）→ `;` → `". "` → 全都不可用时 `_hard_split` 按固定长度硬切。分隔符**附在非末尾块尾部**（保留语义标点）。
2. `_pack(pieces)` —— greedy 合并至接近 `chunk_size`；超出时先产出文档，再从**已产出文档尾部取 `chunk_overlap` 个字符作为下一片的种子**。若「种子 + 当前片段」超过 `chunk_size`，则**放弃这一次的重叠**（避免产生纯重复小块）。
3. `iter_split_sections(sections, doc_code, biz_tag)` —— 惰性 yield；`chunk_index` **跨 section 连续递增**；**重叠仅在同一 section 的相邻切片之间保持，不跨 section**，避免跨语义单元污染。

> **关键口径**：分块是**字符级**（不是 token 级）。500/50 指 500 字符 / 50 字符。

#### ③ Embedding 服务（含降级）

```python
# backend/app/core/rag/embeddings.py
EMBEDDING_BATCH_SIZE = 8      # 【关键防御】硬锁定，见下
PSEUDO_BYTES_PER_DIM = 4
DEFAULT_MODEL_NAME = "doubao-embedding-vision"
DEFAULT_EMBEDDING_DIM = 1024
```

**环境变量优先级**（向量与聊天**解耦**）：

| 用途 | 优先键 | 回退键 |
|---|---|---|
| API Key | `EMBEDDING_API_KEY` | `OPENAI_API_KEY` |
| Base URL | `EMBEDDING_BASE_URL` | `OPENAI_BASE_URL` |
| 模型名 | `EMBEDDING_MODEL_NAME` | `doubao-embedding-vision` |
| 维度 | `EMBEDDING_DIM` | `1024` |

```python
class EmbeddingService:
    def __init__(self) -> None:
        self.api_key = (os.getenv(ENV_EMBEDDING_API_KEY) or os.getenv(ENV_FALLBACK_API_KEY, "")).strip()
        self.base_url = os.getenv(ENV_EMBEDDING_BASE_URL) or os.getenv(ENV_FALLBACK_BASE_URL) or None
        self.model_name = os.getenv(ENV_EMBEDDING_MODEL_NAME) or DEFAULT_MODEL_NAME
        self._client = openai.AsyncOpenAI(api_key=self.api_key or "missing", base_url=self.base_url)

    @staticmethod
    def _pseudo_embedding(text: str) -> list[float]:
        """基于内容 MD5 的哈希链生成 EMBEDDING_DIM 维 L2 归一化伪向量。"""
        needed_bytes = EMBEDDING_DIM * PSEUDO_BYTES_PER_DIM
        digest = hashlib.md5(text.encode("utf-8")).digest()
        byte_stream = bytearray()
        while len(byte_stream) < needed_bytes:
            byte_stream.extend(digest)
            digest = hashlib.md5(digest).digest()     # 哈希链：前一 digest 派生后一 digest
        raw_bytes = bytes(byte_stream[:needed_bytes])
        values = [float(struct.unpack_from("<i", raw_bytes, offset)[0])
                  for offset in range(0, needed_bytes, PSEUDO_BYTES_PER_DIM)]
        norm = math.sqrt(sum(v * v for v in values))
        if norm == 0:
            values[0] = 1.0; norm = 1.0
        return [value / norm for value in values]
```

**降级触发条件**（`get_embeddings` 内的 `except` 链）：

| 捕获类型 | 触发场景 |
|---|---|
| `openai.APITimeoutError` | 超时 |
| `openai.APIConnectionError` | 连接失败 / Key 缺失时主动 `raise` |
| `openai.RateLimitError` | 限流 |
| `openai.APIError` | 服务端错误 |
| **`ValueError`** | 供应商返回空 data —— openai SDK 抛裸 `ValueError("No embedding data received")`，**不属于 APIError 体系，必须显式纳入** |
| `Exception`（兜底） | 任何未预期异常，`logger.exception` 后同样降级 |

> **降级是完全静默的**：只 `logger.warning`，**不置标志位、不落库、不影响 HTTP 响应**。调用方无法从返回值判断拿到的是真向量还是伪向量 —— 这是第四章场景 A 必须写探针脚本的根本原因。

**批大小硬锁 8 的原因**（源码注释原文）：实测当前编码套餐的 embeddings 入口存在批量行为异常 —— 一次请求文本数 **≥ 16** 时，返回的向量会落入与小批量（≤8）**不同的表示空间**（二者余弦 ≈ 0、完全正交）。入库若按大批量发送而查询只发单条，两边向量空间不一致会导致检索全部失效。

#### ④ 向量存储中枢

```python
# backend/app/core/rag/vector_service.py
DEFAULT_BATCH_SIZE = 50
DEFAULT_DOC_VERSION = "v1.0"
DEFAULT_TOP_K = 3
DEFAULT_MIN_SIMILARITY = 0.5

_SIMILARITY_FROM_DISTANCE = "1 - (embedding <=> CAST(:vec AS vector))"
```

**入库（幂等防重）**：

```python
async def batch_upsert_chunks(self, chunks: Iterable[DocumentChunk],
                               doc_version: str = DEFAULT_DOC_VERSION,
                               batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """分批消费切片流并入库，返回实际新插入记录总数（幂等防重）。"""
```

每批（`_flush_batch`）的处理：

1. 按本批涉及的 `doc_code` 一次性查出库中**已存在的全部切片内容**；
2. 构建去重集合 `{(doc_code, content.strip())}`；
3. 过滤出 `new_chunks`；为空 → 直接返回 0（**这就是幂等机制**）；
4. `await self._embeddings.get_embeddings([...])` 批量向量化；
5. `session.add_all(records)` → `commit()` → 返回插入数。

> 去重键是 `(doc_code, content.strip())`，**不含 `biz_tag`**；也不使用 `DocumentChunk.content_hash`。

**检索（高级混合过滤）**：

```python
async def search_advanced(self, query: str, biz_tag: str | None = None,
                          doc_code: str | None = None,
                          top_k: int = DEFAULT_TOP_K,
                          min_similarity: float = DEFAULT_MIN_SIMILARITY,
                          ) -> list[dict[str, Any]]:
    """高级向量检索：元数据预过滤 + HNSW 余弦距离 + 相似度阈值。"""
```

生成的 SQL（`biz_tag` 与 `doc_code` 为 `None` 时对应子句不拼入）：

```sql
SELECT doc_code, biz_tag, section_title, content,
       1 - (embedding <=> CAST(:vec AS vector)) AS similarity
FROM ai_knowledge_base
WHERE is_active = TRUE
  [AND biz_tag = :biz_tag]
  [AND doc_code = :doc_code]
  AND (1 - (embedding <=> CAST(:vec AS vector))) >= :min_sim
ORDER BY embedding <=> CAST(:vec AS vector)
LIMIT :top_k
```

- 向量以**字面值字符串**传入：`"[" + ",".join(f"{value:.8f}") + "]"` → `CAST(:vec AS vector)`。
- 距离算子 `<=>` 是 pgvector 的**余弦距离**；`1 - distance` 即余弦相似度。
- `is_active = TRUE` 是**恒定**过滤条件（软删除的切片不参与检索）。

**软删除**：

```python
async def soft_delete_document(self, doc_code: str) -> int:
    """按 doc_code 软删除（is_active=FALSE），返回影响行数。"""
```

> ⚠️ **没有 un-delete 路径**（见第五章）。

---

## 2.4 通用工作流引擎与状态机底座

### 模块职责

提供与业务无关的状态机运行骨架：跨业务基类状态、进程内图注册中心（依赖反转）、人机协同控制器（CAS 抢占 + 唤醒 + 待办 + 终态）、线程映射仓储、消息/卡片持久化。

### 核心源码文件路径

| 文件 | 职责 |
|---|---|
| [`backend/app/core/workflow/base_state.py`](backend/app/core/workflow/base_state.py) | `BaseWorkflowState`（TypedDict 基石） |
| [`backend/app/core/workflow/graph_registry.py`](backend/app/core/workflow/graph_registry.py) | `GraphRegistry`（进程内注册表） |
| [`backend/app/core/workflow/hitl.py`](backend/app/core/workflow/hitl.py) | `HITLController` |
| [`backend/app/core/workflow/thread_mapping_store.py`](backend/app/core/workflow/thread_mapping_store.py) | `ThreadMappingStore` |
| [`backend/app/core/workflow/message_recorder.py`](backend/app/core/workflow/message_recorder.py) | `MessageRecorder` |
| [`backend/app/core/workflow/__init__.py`](backend/app/core/workflow/__init__.py) | 统一导出 |

### 关键数据表结构

本模块操作两张表（结构已在 [2.2](#22-数据库双池隔离与并发乐观锁cas) 与 [2.5](#25-动态交互协议a2ui-组件协议--sse-流式推送与前端三栏工作台状态管理) 详述）：

- `ai_thread_mappings` —— 线程/会话映射中枢（含 `lock_version` CAS 版本号）
- `ai_chat_messages` —— 消息与卡片快照（含 `card_payload` / `retry_payload` **JSONB**）

### 核心类与函数签名及内部实现逻辑

#### 基石状态

```python
# backend/app/core/workflow/base_state.py
class BaseWorkflowState(TypedDict):
    """所有垂直业务工作流状态的通用基类。"""
    thread_id: str        # 引擎线程 ID
    session_id: str       # 前端会话 ID
    user_id: str          # 发起人 ID
    status: str           # 流程状态
    error: str | None     # 异常信息（正常为 None）
```

**恰好 5 个字段**，跨业务通用。业务插件通过继承扩展：

```python
# backend/app/plugins/power_grid/states.py
class DispatchState(BaseWorkflowState):
    """检修调度状态：在通用基石上扩展电网业务字段。"""
    substation: str
    voltage_level: str
    operation_task: str
    safety_measures: list[str]
    violations: list[str]
    biz_order_id: str | None
    audit_decision: dict | None
    permit_info: dict | None
```

#### 图注册中心（依赖反转）

```python
# backend/app/core/workflow/graph_registry.py
DEFAULT_GRAPH_NAME = "DEFAULT"

class GraphRegistry:
    """已编译工作流图的进程内注册表。"""
    _graphs: dict[str, Any] = {}

    @classmethod
    def register_graph(cls, name: str, graph: Any) -> None: ...

    @classmethod
    def get_graph(cls, name: str = DEFAULT_GRAPH_NAME) -> Any:
        graph = cls._graphs.get(name)
        if graph is None:
            raise RuntimeError(
                "未找到已注册的工作流图，请确认是否已执行 register_graph"
                f"（请求 name={name}）。"
            )
        return graph

    @classmethod
    def clear(cls) -> None: ...
```

> **底座不 import 任何业务图**。图由插件在装配期注册（`main.py` lifespan 或测试 bootstrap）。注册名**必须显式传**（`power_grid`），避免业务图漏传 `graph_name` 时静默唤醒另一业务的图。

#### 消息记录器

```python
# backend/app/core/workflow/message_recorder.py
KIND_CARD = "card"
KIND_TEXT = "text"

class MessageRecorder:
    """无状态消息记录器（静态方法）。"""

    @staticmethod
    async def record_card(thread_id: str, role: str, card_type: str,
                          card_payload: dict[str, Any],
                          retry_payload: dict[str, Any] | None = None,
                          content: str | None = None) -> AIChatMessage: ...

    @staticmethod
    async def record_text(thread_id: str, role: str,
                          content: str) -> AIChatMessage: ...

    @staticmethod
    async def list_by_thread(thread_id: str) -> list[dict[str, Any]]:
        """按 thread_id 读取消息 / 卡片快照，按 created_at 升序；无记录返回 []。"""
```

- `record_card` 写 `kind='card'`，同时把**自包含的重试载荷**（`retry_payload`）一并落库 —— 前端拿到卡片后无需回查即可重试。
- `list_by_thread` 用裸 SQL 读出 9 列；JSONB 由驱动还原为 `dict`；`created_at` 转 ISO 字符串。

#### 电力业务状态机拓扑【源码】

[`backend/app/plugins/power_grid/graph.py`](backend/app/plugins/power_grid/graph.py)：

```
START ──► safety_check ──┬──(no violations)──► oms_draft ──► human_audit ──┬──(is_permitted)──► issue_permit ──► END
                          │                                                   │
                          └──(violations)──► END                            └──(rejected)──► END
```

四个节点与两个条件边：

| 节点 | 职责 | 关键实现 |
|---|---|---|
| `safety_check` | 安规校验 | 关键词子串匹配「接地线」「验电」 |
| `oms_draft` | 建 OMS 正式工单 | `OMSGatewayAdapter.create_official_order(...)` → `{"biz_order_id": ...}` |
| `human_audit` | **挂起等待调度长核签** | 节点内 `interrupt({...})`，resume 值即审核结论 |
| `issue_permit` | 签发调度许可令 | `SCADAGatewayAdapter.issue_credential(...)` → `{"permit_info": ...}` |

```python
def build_dispatch_graph(checkpointer=None):
    """编译电网检修调度图并返回。
    人工挂点由节点内 interrupt() 表达，不使用 interrupt_before。
    checkpointer 缺省退化为内存检查点（测试）。"""
    builder = StateGraph(DispatchState)
    builder.add_node("safety_check", safety_check_node)
    builder.add_node("oms_draft", oms_draft_node)
    builder.add_node("human_audit", human_audit_node)
    builder.add_node("issue_permit", issue_permit_node)

    builder.add_edge(START, "safety_check")
    builder.add_conditional_edges("safety_check", route_after_safety_check,
                                  ["oms_draft", END])
    builder.add_edge("oms_draft", "human_audit")
    builder.add_conditional_edges("human_audit", route_after_audit,
                                  ["issue_permit", END])
    builder.add_edge("issue_permit", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())
```

> **挂起点用节点内 `interrupt()`，不是 `interrupt_before`**。这带来一个重要行为差异：`interrupt()` 会在节点**执行到一半**时挂起，`snapshot.interrupts` 非空；而 `interrupt_before` 是在节点**开始前**挂起。插件 `router.py` 正是用 `bool(snapshot.interrupts)` 来判定「图是否真的挂起了」。

---

## 2.5 动态交互协议（A2UI 组件协议 / SSE 流式推送）与前端三栏工作台状态管理

### 模块职责

定义**跨业务、行业中立**的扁平事件协议（A2UI），后端以 SSE 单向推流；前端按 `card_type` 动态解析卡片组件，并用三栏工作台收集中栏消息、左栏会话集合、右栏抽屉。

### 核心源码文件路径

**后端（协议与网关）**：

| 文件 | 职责 |
|---|---|
| [`backend/app/schemas/a2ui.py`](backend/app/schemas/a2ui.py) | 协议定义：`A2UIEventType` / `AgentChatRequest` / `AgentChatEvent` |
| [`backend/app/api/v1/agent.py`](backend/app/api/v1/agent.py) | SSE 网关：分帧、建档、落库、留痕、错误收口 |

**前端（协议消费与工作台）**：

| 文件 | 职责 |
|---|---|
| [`frontend/src/core/api/agent.ts`](frontend/src/core/api/agent.ts) | SSE 客户端（`@microsoft/fetch-event-source`） |
| [`frontend/src/core/a2ui/types.ts`](frontend/src/core/a2ui/types.ts) | 前端协议类型（与后端 `AIChatMessage` 对齐） |
| [`frontend/src/core/a2ui/CardRegistry.ts`](frontend/src/core/a2ui/CardRegistry.ts) | 卡片类型 → 组件 的注册中枢 |
| [`frontend/src/core/a2ui/MessageCardHost.vue`](frontend/src/core/a2ui/MessageCardHost.vue) | 卡片宿主（动态组件渲染） |
| [`frontend/src/core/workbench/useWorkbenchStore.ts`](frontend/src/core/workbench/useWorkbenchStore.ts) | 三栏共享响应式状态 |
| [`frontend/src/core/engine/storage.ts`](frontend/src/core/engine/storage.ts) | IndexedDB 持久化（1000ms 防抖） |
| [`frontend/src/core/engine/render_ticker.ts`](frontend/src/core/engine/render_ticker.ts) | 打字机渲染器 |
| [`frontend/src/core/views/WorkbenchLayout.vue`](frontend/src/core/views/WorkbenchLayout.vue) | 三栏布局 |
| [`frontend/src/core/views/TaskApprovalPool.vue`](frontend/src/core/views/TaskApprovalPool.vue) | 待办审批看板 |

### 关键数据表结构

#### `ai_chat_messages` —— 交互载荷与卡片快照【源码】

| 列名 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `id` | `String(64)` | **PK**, 默认 `uuid4` | |
| `thread_id` | `String(64)` | NOT NULL | 逻辑关联到 `ai_thread_mappings.thread_id`（**无物理外键**） |
| `role` | `String(16)` | NOT NULL | `user` / `assistant` |
| `kind` | `String(16)` | `server_default='text'`, NOT NULL | `text` / `card` |
| `content` | `Text` | NULL | 文本内容 |
| `card_type` | `String(32)` | NULL | 卡片类型（如 `dispatcher_audit` / `permit_result` / `power_grid_citations`） |
| **`card_payload`** | **`JSONB`** | NULL | 卡片结构体 |
| **`retry_payload`** | **`JSONB`** | NULL | 自包含重试载荷（如 `{"thread_id":..., "lock_version":1}`） |
| `is_sanitized` | `Boolean` | `server_default=false`, NOT NULL | 是否已净化（预留字段，当前无写入方） |
| `created_at` | `DateTime(tz)` | `server_default=now()`, NOT NULL | |

**索引**：`idx_chat_thread_created` —— btree `(thread_id, created_at)`（支撑按线程 + 时间序读取）。

#### 协议定义

```python
# backend/app/schemas/a2ui.py
class A2UIEventType(str, Enum):
    """A2UI 聚合网关扁平事件类型（顶层字段平铺）。"""
    TOKEN   = "token"    # {"type": "token", "content": ...}
    UI_CARD = "ui_card"  # {"type": "ui_card", "card_type": ..., "data": {...}}
    ERROR   = "error"    # {"type": "error", "message": ...}
    DONE    = "done"     # {"type": "done"}
```

```python
class AgentChatRequest(BaseModel):
    thread_id: str = Field(..., description="会话线程 ID（Checkpointer 持久化键，多轮上下文以此隔离）")
    session_id: str = Field(default="", description="前端 UI 会话 ID")
    message: str = Field(default="", description="用户输入文本")
    action_payload: Optional[dict[str, Any]] = Field(None, description="前端卡片操作回传载荷…")

class AgentChatEvent(BaseModel):
    type: A2UIEventType
    content: Optional[str] = None
    card_type: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    message: Optional[str] = None
```

> ⚠️ **`action_payload` 在后端没有任何消费方** —— `api/v1/agent.py` 从不读取它（见第五章）。

### 核心类与函数签名及内部实现逻辑

#### 后端 SSE 网关

```python
# backend/app/api/v1/agent.py
agent_router = APIRouter(prefix="/agent", tags=["Universal-Agent"])

CHAT_THREAD_PREFIX = "chat_"          # 聊天线程命名空间前缀（与业务工单线程隔离）
CHAT_IDEMPOTENCY_PREFIX = "chat:"     # 幂等键前缀
ROLE_USER = "assistant"                # 实际取值见下
ROLE_ASSISTANT = "assistant"

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",         # 禁用 Nginx 缓冲，保证逐字推流
}
```

```python
def build_chat_thread_id(thread_id: str) -> str:
    """聊天线程统一加命名空间前缀（幂等）。"""
    if thread_id.startswith(CHAT_THREAD_PREFIX):
        return thread_id
    return f"{CHAT_THREAD_PREFIX}{thread_id}"
```

```python
def _sse_frame(event_name: str, payload: dict[str, Any]) -> str:
    """渲染一帧 SSE（event 名 + data JSON）。"""
    body = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_name}\ndata: {body}\n\n"

def _sse_event(event: AgentChatEvent) -> str:
    """把扁平事件渲染为 SSE 帧。"""
    payload = event.model_dump(mode="json", exclude_none=True)
    return _sse_frame(event.type.value, payload)
```

> `exclude_none=True` ⇒ **None 字段不会出现在 `data:` 里**。例如 `done` 事件的 data 就是 `{"type":"done"}` 而非 `{"type":"done","content":null,...}`。

**端点主流程**（`POST /api/v1/agent/chat-stream`）：

```python
@agent_router.post("/chat-stream")
async def chat_stream(req: AgentChatRequest,
                      current_user: dict = Depends(get_current_user),
                      ) -> StreamingResponse:
```

1. 取活跃插件的 `chat_handler`（`PluginLoader.active().chat_handler`）；为 `None` → 推 `error` 帧 + `done` 帧并返回（**不 500**）。
2. 计算 `physical_thread_id = build_chat_thread_id(req.thread_id)`。
3. `ThreadMappingStore.create_mapping(...)`：`assigned_role=ROLE_SYSTEM`、`status=STATUS_ACTIVE`、`idempotency_key=f"chat:{physical_thread_id}"`。
4. `req.message` 非空 → `MessageRecorder.record_text(role="user")`。
5. 构造 `ChatContext`（含 `trace_sink=TraceWriter(thread_id)`）。
6. 遍历 `handler(context, req)` 的异步事件流：逐个 `_sse_event` 推帧；`token` 类型的内容累积到 `collected`。
7. 异常 → `failure = f"对话执行异常：{type(exc).__name__}"`。
8. `collected` 非空 → `MessageRecorder.record_text(role="assistant", content=answer)`（**成功与异常路径都保留已产出内容**）。
9. `failure is not None` → 推 `error` 帧并 `return`（⚠️ **此路径下不会再有 `done` 帧**）；否则推 `done` 帧。

**事件序列契约**：

```
正常：  token*  →  ui_card(可选)  →  done
无召回：token(单帧)  →  done          ← 插件提前 return，无 ui_card
异常：  token*(可能) →  error          ← 无 done
无 handler：error → done
```

#### 前端 SSE 客户端

```typescript
// frontend/src/core/api/agent.ts
export const CHAT_STREAM_PATH = '/v1/agent/chat-stream'
export type ChatEventType = 'token' | 'ui_card' | 'error' | 'done'
export type StreamStatus = 'idle' | 'connected' | 'reconnecting' | 'offline'
export const RECONNECT_INTERVAL_MS = 2000
export const MAX_RECONNECT_ATTEMPTS = 3

export async function chatStream(
  request: ChatStreamRequest,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void>
```

关键行为：

| 环节 | 实现 |
|---|---|
| 传输 | `fetchEventSource(url, { method: 'POST', body, headers: { Accept: 'text/event-stream', Authorization: 'Bearer ...' } })` |
| 连接校验 | `onopen` 检查 `response.ok` 与 `content-type.startsWith('text/event-stream')`；不满足则抛 **fatal** 错误（立即终止重连） |
| 事件分派 | `onmessage` 中 `JSON.parse(message.data)`；解析失败**静默忽略**（心跳注释等非 JSON 负载），不中断流 |
| 重连 | `onerror` 中 `retryCount++`；fatal 或 `retryCount > 3` → 状态置 `offline` 并抛出以终止库内置重连；否则置 `reconnecting` 并返回 2000（毫秒）间隔 |
| 正常收口 | `onclose`：`finished`（收到过 `done`）→ `connected`，否则 → `offline` |
| 状态灯语义 | `idle` 表示**当前没有进行中的对话流**，**不代表后端不可达** |

> **采用 `@microsoft/fetch-event-source` 而非原生 fetch** —— 该库内置事件分帧、TCP Buffer 拼接与断网自动重连，符合项目「Streaming First + 成熟事件流驱动库」的规范。

#### 三栏工作台状态管理

```typescript
// frontend/src/core/workbench/useWorkbenchStore.ts
interface WorkbenchState {
  activeSessionId: string
  activeMessages: ChatMessageRecord[]
  conversationList: TaskSummary[]
  rightDrawerOpen: boolean
}

const state = reactive<WorkbenchState>({ ... })   // ← reactive 单例，非 Pinia
let conversationOwnerId: string | null = null
```

导出的动作函数：

| 函数 | 签名要点 | 行为 |
|---|---|---|
| `setSession(sessionId, messages = [])` | | 替换当前会话 ID 与消息列表（用 `splice` 触发响应式） |
| `appendMessage(message)` | | 追加一条消息 |
| `appendMessageText(id, chunk)` | | 流式打字机逐字写入；消息不存在时**静默忽略** |
| `openConversation(summary)` | `async` | 从 IndexedDB 恢复消息并切换会话 |
| `hydrateConversations(userId)` | `async` | 加载指定用户的会话集合；**归属用户未变则直接返回**（避免覆盖内存新记录） |
| `applyResult(result)` | | 把 `POST /apply` 的返回收口为「中栏消息 + 会话集合 upsert + 折叠右栏」 |
| `setConversations(list)` | | 整体替换左栏列表 |
| `setRightDrawer(open)` | | 右栏抽屉开合 |

**`applyResult` 的三合一收口**（[useWorkbenchStore.ts:96-142](frontend/src/core/workbench/useWorkbenchStore.ts#L96-L142)）：

```typescript
const message: ChatMessageRecord = {
  id: crypto.randomUUID(),
  thread_id: result.thread_id,
  role: 'assistant',
  kind: text ? 'text' : 'card',        // ← 后端返 message（安规否决）时退化为纯文本
  content: text || null,
  card_type: text ? null : cardType,
  card_payload: text ? null : card,
  retry_payload: null,
  created_at: new Date().toISOString(),
}
```

- 左栏会话条目：`lock_version: Number(card.lock_version ?? 1)`；`title` 优先取 `card.title`，缺省回退展示 `thread_id`。
- 右栏：`state.rightDrawerOpen = false`。

**持久化**（[`frontend/src/core/engine/storage.ts`](frontend/src/core/engine/storage.ts)）：

| 键 | 内容 |
|---|---|
| `session:<sessionId>` | 该会话的消息数组 |
| `conversations:<userId>` | 该用户的会话集合（**按用户隔离**） |

- 专用 localforage 实例：`name: 'agent-scaffold'` / `storeName: 'messages'`。
- **防抖 1000ms** 写盘（`debounceSaveMessages` / `debounceSaveConversations`）—— 推流期间不断重置计时器，`done` 后落盘一次。
- **落盘前必须 `deepToPlain` 剥离 Vue 响应式代理** —— IndexedDB 用结构化克隆，遇到 Proxy 会抛 `DataCloneError`。
- 写盘失败**显式 `console.error`**，不静默吞掉。

---

## 2.6 其他底座辅助模块

### 2.6.1 业务插件装载与隔离

#### 模块职责

实现「**接入新业务 = 新增一个插件目录**，底座零改动」。插件在自身目录内用 `PluginManifest` 自描述路由、状态机工厂、对话能力、端点路径与演示身份；通用底座据此完成装配。

#### 核心源码文件路径

| 文件 | 职责 |
|---|---|
| [`backend/app/core/plugin/manifest.py`](backend/app/core/plugin/manifest.py) | `PluginManifest` 契约 + `ChatContext` + `ChatHandler` / `TraceSink` Protocol |
| [`backend/app/core/plugin/loader.py`](backend/app/core/plugin/loader.py) | `PluginLoader` —— 发现 / 生效选择 / 身份登记 |
| [`backend/scripts/check_plugin_isolation.py`](backend/scripts/check_plugin_isolation.py) | **CI 隔离门禁**（24 词黑名单） |
| [`backend/app/api/v1/plugin.py`](backend/app/api/v1/plugin.py) | `GET /plugin/manifest` —— 后端是端点路径与演示身份的唯一真相源 |

#### 清单契约

```python
# backend/app/core/plugin/manifest.py
API_PREFIX = "/api"
ENDPOINT_TASKS = "tasks"; ENDPOINT_MESSAGES = "messages"
ENDPOINT_RESUME = "resume";  ENDPOINT_APPLY = "apply"

@dataclass(frozen=True)
class PluginManifest:
    name: str                              # 插件唯一名（须与目录名一致）
    version: str                           # 语义化版本（前后端偏斜检测用）
    router: APIRouter                      # 路由（自身不带前缀）
    router_prefix: str                     # 挂载前缀（含 /api）
    graph_factory: GraphFactory | None = None
    graph_name: str = ""                   # GraphRegistry 键，必须显式传
    chat_handler: ChatHandler | None = None
    endpoint_paths: Mapping[str, str] = field(default_factory=dict)
    identities: tuple[PluginIdentity, ...] = ()
```

**4 项契约校验**（`__post_init__`，任一不满足抛 `PluginContractError`）：

| # | 校验 |
|---|---|
| 1 | `name` 非空 |
| 2 | `version` 非空 |
| 3 | `router_prefix` 必须以 `/api` 开头 |
| 4 | 声明了 `graph_factory` 就**必须**同时给出 `graph_name` |

**端点绝对路径解析**：

```python
@property
def endpoints(self) -> dict[str, str]:
    """例：router_prefix=/api/v1/sample-biz + {"tasks": "/tasks"}
        → "/v1/sample-biz/tasks"（相对 /api，与前端 http baseURL 对齐）"""
    base = self.router_prefix.removeprefix(API_PREFIX).rstrip("/")
    ...
```

#### 生效插件选择（确定性优先，绝不隐式猜测）

```python
# backend/app/core/plugin/loader.py
ACTIVE_PLUGIN_ENV = "ACTIVE_PLUGIN"
PLUGIN_MODULE_NAME = "plugin"
PLUGIN_ATTR_NAME = "PLUGIN"

class PluginLoader:
    _active: PluginManifest | None = None

    @classmethod
    def discover(cls) -> dict[str, PluginManifest]:
        """扫描 app/plugins/*/plugin.py，返回 {插件名: 清单}。"""

    @classmethod
    def load_active(cls) -> PluginManifest:
        """确定并缓存生效插件清单（每次调用都重新发现）。"""

    @classmethod
    def active(cls) -> PluginManifest: ...
    @classmethod
    def clear(cls) -> None: ...
```

`discover()` 的**发现规则**：

- 遍历 `app/plugins/` 下的子包；`_` 前缀的跳过。
- 子包**没有 `plugin.py`** → `ModuleNotFoundError.name == module_path` → 视为非插件子包，`logger.debug` 跳过。
- 插件模块**其他依赖缺失** → `ModuleNotFoundError` 但 `exc.name != module_path` → **直接向上抛出**（fail-fast，绝不静默跳过）。
- `plugin.py` 未导出 `PLUGIN` → `logger.warning` 跳过。
- `PLUGIN` 不是 `PluginManifest` 实例 → `PluginContractError`。
- `manifest.name != 目录名` → `PluginContractError`（清单 name 与目录名必须一致）。

`load_active()` 的**选择规则**（优先级从上到下）：

1. `ACTIVE_PLUGIN` 环境变量显式指定 → 匹配不到则 `PluginContractError`（并列出可用插件）。
2. 未设且**只有一个**插件 → 自动选中。
3. 未设且有**多个**插件 → `PluginContractError("检测到多个业务插件 …，请通过环境变量 ACTIVE_PLUGIN 指定生效插件。")`。
4. 一个插件都没发现 → `PluginContractError`。

选中后调用 `_seed_identities(manifest)`，把插件声明的演示身份逐个登记进 `IAMGatewayAdapter.register_user(...)`。

> **装配时机**：`active_plugin = PluginLoader.load_active()` 位于 [`backend/main.py:40`](backend/main.py#L40) —— **模块 import 期**执行。契约违规 / 无法确定生效插件 → **进程启动即失败**。

#### 隔离门禁

[`backend/scripts/check_plugin_isolation.py`](backend/scripts/check_plugin_isolation.py)：
- **扫描范围**：`backend/app/core/`、`backend/app/schemas/a2ui.py`、`backend/app/api/v1/agent.py`、`backend/app/api/v1/plugin.py`、`backend/app/services/acl/`、`frontend/src/core/`。
- **黑名单**：24 条业务词汇（`power_grid`、`OMS`、`SCADA`、`dispatcher_audit`、`变电站`、`安规`、`kV`、`DISPATCHER`、`applicant_0\d` 等）。
- **豁免**：行内 `@isolation-exempt` 标记可跳过该行。
- **退出码**：0 = 通过，1 = 检出违规。

### 2.6.2 防腐层（Anti-Corruption Layer）标准契约

#### 核心源码文件路径

[`backend/app/services/acl/protocols.py`](backend/app/services/acl/protocols.py) —— 三个 `@runtime_checkable` Protocol：

```python
@runtime_checkable
class IAMAdapterProtocol(Protocol):
    def verify_token(self, token: str) -> dict[str, Any]: ...

@runtime_checkable
class OrderAdapterProtocol(Protocol):
    async def create_official_order(self, draft_data: dict[str, Any],
                                    creator_id: str) -> str: ...
    async def update_order_status(self, biz_order_id: str, new_status: str,
                                  audit_opinion: str | None = None) -> bool: ...

@runtime_checkable
class CredentialAdapterProtocol(Protocol):
    async def issue_credential(self, biz_order_id: str,
                               reviewer_id: str) -> dict[str, Any]: ...
```

> 实现方**无需显式继承** —— 只要方法签名一致即视为该协议的实现（duck typing 的静态化）。

**当前实现（全部为 Mock）**：

| 适配器 | 文件 | 行为 |
|---|---|---|
| `IAMGatewayAdapter` | [`backend/app/services/acl/iam_adapter.py`](backend/app/services/acl/iam_adapter.py) | 本地 JWT 签发/校验（见 2.1） |
| `OMSGatewayAdapter` | [`backend/app/plugins/power_grid/adapters/oms_adapter.py`](backend/app/plugins/power_grid/adapters/oms_adapter.py) | 工单号 `OMS-YYYYMMDD-NNNNNN`（`secrets.randbelow(10**6)`）；`update_order_status` **只打日志** |
| `SCADAGatewayAdapter` | [`backend/app/plugins/power_grid/adapters/scada_adapter.py`](backend/app/plugins/power_grid/adapters/scada_adapter.py) | 许可令 `DISP-YYYYMMDD-XXXXXXXX`（8 位大写 HEX）；`ca_signature_hash = sha256("permit_no|biz_order_id|reviewer_id|APPROVED")` |

**替换真实系统的契约**：外部 HTTP 调用只需替换对应类内部实现，**对外静态方法签名保持不变**。

### 2.6.3 执行留痕（Trace）与可观测性

#### 核心源码文件路径

[`backend/app/api/v1/agent.py:76-110`](backend/app/api/v1/agent.py#L76-L110) —— `TraceWriter`；表定义在 [`backend/app/models/ai_schema.py:135-165`](backend/app/models/ai_schema.py#L135-L165)。

```python
class TraceWriter:
    """执行留痕写入器（通用层实现 ai_execution_traces 落库）。"""

    def __init__(self, thread_id: str) -> None:
        self._thread_id = thread_id

    async def record(self, node_name: str, model_name: str,
                     prompt_tokens: int = 0, completion_tokens: int = 0,
                     latency_ms: int = 0, total_cost: float = 0.0,
                     tool_calls: dict[str, Any] | None = None,
                     error_log: str | None = None) -> None:
        """写入一行节点级留痕；写失败仅告警，不影响主对话链路。"""
```

- 通过 `ChatContext.trace_sink`（`TraceSink` Protocol）**依赖倒置**注入 —— 通用层负责写入，插件只上报观测数据。
- 写入失败 → `logger.exception`，**不阻断对话**（旁路审计语义）。

#### 关键数据表结构：`ai_execution_traces`

| 列名 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `id` | `String(64)` | **PK**, 默认 `uuid4` | |
| `thread_id` | `String(64)` | `index=True`, NOT NULL | |
| `node_name` | `String(64)` | NOT NULL | 节点名（当前仅 `chat.stream`） |
| `model_name` | `String(64)` | NOT NULL | 生效模型名（`resolve_model_name()`） |
| `prompt_tokens` | `Integer` | `server_default=0`, NOT NULL | |
| `completion_tokens` | `Integer` | `server_default=0`, NOT NULL | |
| `total_cost` | `Numeric(10,4)` | `server_default=0.0000`, NOT NULL | |
| `latency_ms` | `Integer` | NOT NULL | |
| `tool_calls` | `JSONB` | NULL | 工具调用记录 |
| `error_log` | `Text` | NULL | 异常信息 |
| `created_at` | `DateTime(tz)` | `server_default=now()`, NOT NULL | |

> ⚠️ **覆盖边界（重要）**：`TraceWriter` 的唯一调用方是 [`backend/app/plugins/power_grid/chat.py:176-184`](backend/app/plugins/power_grid/chat.py#L176-L184)。因此：
> 1. **状态机四个节点（`safety_check`/`oms_draft`/`human_audit`/`issue_permit`）一条 trace 都不写**；
> 2. 检索为空时 `chat.py` 提前 `return`，**连 chat 自己的 trace 也不写**。

### 2.6.4 应用装配与生命周期

[`backend/main.py`](backend/main.py)：

```python
# ① Windows 事件循环策略 —— 必须在 import psycopg 之前
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ② 加载 .env —— 按绝对路径定位，不依赖进程工作目录
load_dotenv(Path(__file__).resolve().parent / ".env")

# ③ 生效业务插件：模块级装载 —— 契约违规 / 无法确定时启动即失败
active_plugin = PluginLoader.load_active()
```

**lifespan 启停顺序**：

| 阶段 | 动作 |
|---|---|
| 启动 | `await checkpointer_manager.init_pool()`（开池 + `saver.setup()` 幂等建 4 张 checkpoint 表）→ `active_plugin.graph_factory(saver)` → `GraphRegistry.register_graph(active_plugin.graph_name, graph_app)` → 打印 `[中枢就绪] …` |
| 退出 | `graph_app = None` → `await checkpointer_manager.close_pool()` → `await async_engine.dispose()` → 打印 `[中枢关停] …` |

**路由挂载**：

```python
app.include_router(auth_router,     prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(agent_router,     prefix="/api/v1")
app.include_router(plugin_router,    prefix="/api/v1")
app.include_router(active_plugin.router, prefix=active_plugin.router_prefix)
```

**健康探针**：

```python
@app.get("/api/v1/health")
async def health_check() -> dict:
    return {"code": 200, "status": "ok",
            "plugin": active_plugin.name,
            "graph_ready": graph_app is not None}
```

> `graph_ready: true` 表示「检查点池已开 + 4 张 checkpoint 表已建 + 状态图已注册进 `GraphRegistry`」——**这是一站式的后端就绪断言**。

**当前没有的能力**【源码】：无 `StaticFiles` 挂载、无全局异常处理器、无请求 ID / 链路追踪中间件、无 CORS 之外的任何中间件、无 API 版本化策略（版本写死在路径前缀）。

---

# 第三章 三大核心动线全链路穿透解析

## 3.1 动线一：系统底层逻辑动线（Logic Flow）

> **前端 → 鉴权 → 状态机 → 数据库读写/向量召回 → 大模型 → SSE 回传**

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 浏览器                                                                  │
│  core/api/agent.ts :: chatStream()                                       │
│      POST /api/v1/agent/chat-stream   (Accept: text/event-stream)        │
│      Authorization: Bearer <JWT>                                        │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │  ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ FastAPI 路由层                                                           │
│  api/v1/agent.py :: chat_stream(req, current_user=Depends(get_current_user))│
└───────┬──────────────────────────────────────────────┬───────────────────┘
        │                                              │
        │ Depends 链                                   │ 业务处理
        ↓                                              ↓
┌──────────────────────────────┐   ┌──────────────────────────────────────┐
│ core/security.py             │   │ PluginLoader.active().chat_handler   │
│  get_current_user()          │   │  = plugins/power_grid/chat.py        │
│    → IAMGatewayAdapter       │   │      :: power_grid_chat_handler()    │
│      .verify_token(token)    │   └───────────────┬──────────────────────┘
│  (HS256 / 12h / sub,name,    │                   │
│   role,dept,iat,exp)        │                   │ ① 召回规程条款
│  失败 → 401                  │                   ↓
└──────────────────────────────┘   ┌──────────────────────────────────────┐
                                   │ core/rag/vector_service.py           │
                                   │  VectorStoreService.search_advanced()│
                                   │   ├─ EmbeddingService.get_embeddings()│
                                   │   │    （失败 → MD5 伪向量降级）      │
                                   │   └─ SELECT … embedding <=> CAST(…)  │
                                   │        FROM ai_knowledge_base         │
                                   │        WHERE is_active [AND biz_tag] │
                                   │          AND similarity >= :min_sim  │
                                   │        ORDER BY <=> LIMIT :top_k     │
                                   │   → HNSW 索引 idx_knowledge_…_hnsw   │
                                   └───────────────┬──────────────────────┘
                                                   │ ② 大模型生成
                                                   ↓
                                   ┌──────────────────────────────────────┐
                                   │ core/llm.py :: build_chat_model()     │
                                   │  → ChatOpenAI.astream(messages)       │
                                   │    (temperature=0.1, 逐 chunk 增量)   │
                                   └───────────────┬──────────────────────┘
                                                   │
                                                   ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ api/v1/agent.py :: event_stream()                                        │
│  ┌── SSE 分帧 ────────────────────────────────────────────────┐          │
│  │ event: token   data: {"type":"token","content":"…"}        │          │
│  │ event: ui_card data: {"type":"ui_card","card_type":"…"}    │          │
│  │ event: done    data: {"type":"done"}                       │          │
│  └────────────────────────────────────────────────────────────┘          │
│  旁路：MessageRecorder.record_text() → ai_chat_messages                  │
│  旁路：TraceWriter.record()           → ai_execution_traces              │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ StreamingResponse(text/event-stream)
                                │   + X-Accel-Buffering: no
                                ↓
┌──────────────────────────────────────────────────────────────────────────┐
│ 浏览器                                                                  │
│  core/api/agent.ts :: onmessage → dispatch(payload)                      │
│    'token'   → onToken(content)                                         │
│    'ui_card' → onCard(card_type, data)                                  │
│    'error'   → onError(message)                                         │
│    'done'    → onDone()                                                 │
│  core/engine/render_ticker.ts 打字机渲染                                │
│  core/workbench/useWorkbenchStore.ts.appendMessageText() 逐字写入       │
│  core/engine/storage.ts  debounceSaveMessages(1000ms) → IndexedDB       │
└──────────────────────────────────────────────────────────────────────────┘
```

### 逐步骤调用链

| # | 位置 | 动作 | 落库 / 副作用 |
|---|---|---|---|
| 1 | `frontend/src/core/api/agent.ts::chatStream` | 组装请求，`fetchEventSource` POST + SSE | — |
| 2 | `backend/app/api/v1/agent.py::chat_stream` | 取 `manifest.chat_handler`；计算 `physical_thread_id = build_chat_thread_id(req.thread_id)` | — |
| 3 | `core/security.py::get_current_user` → `services/acl/iam_adapter.py::IAMGatewayAdapter.verify_token` | 校验 JWT | — |
| 4 | `core/workflow/thread_mapping_store.py::ThreadMappingStore.create_mapping` | 建档（幂等） | `ai_thread_mappings`（`assigned_role='SYSTEM'`, `status='ACTIVE'`, `idempotency_key='chat:<tid>'`） |
| 5 | `core/workflow/message_recorder.py::MessageRecorder.record_text(role='user')` | 用户消息落库 | `ai_chat_messages` |
| 6 | `plugins/power_grid/chat.py::power_grid_chat_handler` | 取插件 handler，构造 `ChatContext`（含 `trace_sink`） | — |
| 7 | `core/rag/vector_service.py::VectorStoreService.search_advanced` | 召回（`biz_tag='power_grid'`, `top_k=3`, `min_similarity=0.3`） | 读 `ai_knowledge_base` |
| 8 | ↳ `core/rag/embeddings.py::EmbeddingService.get_embeddings` | 查询向量（批量 8）；异常 → `_pseudo_embedding` | — |
| 9 | ↳ 若 `rows` 为空 → `yield TOKEN(NO_RESULT_ANSWER)` 并 **return** | **无 ui_card、无 trace** | — |
| 10 | `core/llm.py::build_chat_model(temperature=0.1)` → `ChatOpenAI.astream` | 逐 chunk 产出增量文本 | — |
| 11 | `api/v1/agent.py::_sse_event` → `_sse_frame` | 逐事件分帧推送 | — |
| 12 | `core/workflow/message_recorder.py::MessageRecorder.record_text(role='assistant')` | 完整回答落库（异常路径也保留已产出部分） | `ai_chat_messages` |
| 13 | `api/v1/agent.py::TraceWriter.record(node_name='chat.stream')` | 留痕（**仅第 10 步走到过**） | `ai_execution_traces` |
| 14 | 前端 `onmessage` → `dispatch` | 事件分派 | — |
| 15 | `core/engine/render_ticker.ts` + `useWorkbenchStore.appendMessageText` | 打字机渲染 | — |
| 16 | `core/engine/storage.ts::debounceSaveMessages` | 1000ms 防抖落 IndexedDB | 浏览器 IndexedDB |

---

## 3.2 动线二：用户前端操作动线（User Operation Flow）

> **登录 / 工作台 → 上传知识库文档 → 发起对话 → HITL 审批 → 查看结果**

```
┌──────────────────────────────────────────────────────────────────────┐
│ ① 打开 http://localhost:5173                                         │
│    App.vue onMounted                                                 │
│      → core/api/plugin.ts::fetchPluginManifest()                     │
│        GET /api/v1/plugin/manifest      （★ 无鉴权）                │
│        → core/plugins/registry.ts::applyManifestEndpoints()          │
│        → core/plugins/registry.ts::applyManifestIdentities()        │
│      → 版本比对（后端 manifest.version vs 本地 plugin.version）      │
│        不一致 → 顶部黄色提示条 + Console.warn                       │
│      → main.ts 的 import.meta.glob 自动装载 src/plugins/*/plugin.ts │
└──────────────────────────────┬───────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│ ② 切换身份（Header 身份下拉）                                        │
│    core/composables/useCurrentUser.ts                                │
│      → POST /api/v1/auth/login  {"user_id":"applicant_01"}           │
│        → api/v1/auth.py::login → IAMGatewayAdapter.create_access_token│
│        → { access_token, token_type:"bearer", user:{sub,name,role,…} }│
│      → localStorage['auth_token'] = access_token                    │
│      → core/workbench/useWorkbenchStore.hydrateConversations(userId) │
│        → IndexedDB: conversations:<userId>                           │
└──────────────────────────────┬───────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│ ③ 三栏工作台 views/WorkbenchLayout.vue                                │
│    左栏 = 我的会话（useWorkbenchStore.conversationList）              │
│    中栏 = 消息流（useWorkbenchStore.activeMessages）                  │
│    右栏 = 抽屉（formComponent / 运行追踪占位）                        │
│    Header SSE 状态灯：idle(灰) / connected(绿) / reconnecting(琥珀)  │
│                                        / offline(红)                 │
└──────────────────────────────┬───────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│ ④ 业务提报（点「📋 快速填报」→ 展开右栏 formComponent）              │
│    plugins/power_grid/forms/SubstationApplyForm.vue                  │
│      → POST /api/v1/power-dispatch/apply   （端点来自后端 manifest） │
│        router.py::apply_dispatch                                      │
│          ① ThreadMappingStore.create_mapping(status=WAITING_HUMAN)  │
│          ② graph.ainvoke({...}, {configurable:{thread_id}})         │
│             safety_check → oms_draft → human_audit(interrupt 挂起)    │
│          ③ snapshot = await graph.aget_state(config)                │
│          ④ interrupted = bool(snapshot.interrupts)                  │
│      ┌──────────── interrupted=True ────────────┐                    │
│      │ record_card(dispatcher_audit)             │                    │
│      │   card_payload {card_type,thread_id,      │                    │
│      │     biz_order_id,substation,voltage_level,│                    │
│      │     operation_task,violations,lock_version}                   │
│      │   retry_payload {thread_id, lock_version} │                    │
│      │ → ai_chat_messages (kind='card')          │                    │
│      │ 返回 {status:"WAITING_HUMAN",            │                    │
│      │       interrupted:true, card:{…}}         │                    │
│      └───────────────────────────────────────────┘                    │
│      ┌──────────── interrupted=False ───────────┐                    │
│      │ finalize_status(SAFETY_REJECTED)          │                    │
│      │ ThreadMappingStore.archive(thread_id)     │                    │
│      │ record_text("安规校验未通过…")             │                    │
│      │ 返回 {status:"SAFETY_REJECTED",           │                    │
│      │       interrupted:false, message, card:{}} │                   │
│      └───────────────────────────────────────────┘                    │
│    前端 useWorkbenchStore.applyResult(result)                         │
│      → 中栏追加消息（card 或 text）+ 左栏 upsert 会话 + 折叠右栏      │
└──────────────────────────────┬───────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│ ⑤ 发起对话（中栏输入框）                                              │
│    core/api/agent.ts::chatStream → （见 3.1 Logic Flow）              │
│    前端打字机 + 引文卡 CitationsCard（card_type=power_grid_citations）│
└──────────────────────────────┬───────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│ ⑥ HITL 审批（切到「王调度长」→ 待办审批池 Tab）                       │
│    views/TaskApprovalPool.vue::activate()                            │
│      → GET /api/v1/power-dispatch/tasks                              │
│        router.py::list_tasks                                          │
│          role==DISPATCHER → HITLController.get_pending_tasks()       │
│          否则              → []（★ 200 + 空列表，不是 403）         │
│      → GET /api/v1/power-dispatch/messages?thread_id=…               │
│        router.py::list_thread_messages（★ 无归属校验）                │
│      → MessageCardHost → SafetyDiffCard                              │
│    ⑦ 点「核准」/「驳回」                                              │
│      → TaskApprovalPool.decide(task, approved)                        │
│      → useWorkflowAction.submitAudit(url, body)                      │
│        body = {thread_id, lock_version, approved, opinion}            │
│      → POST /api/v1/power-dispatch/audit                              │
│        router.py::audit_dispatch                                      │
│          ① require_roles(['DISPATCHER']) → 否则 403                  │
│          ② HITLController.resume_with_cas(...)                        │
│               CAS UPDATE → rowcount==0 ⇒ 409                          │
│               graph.ainvoke(Command(resume={is_permitted,opinion,     │
│                                            reviewer_id}))             │
│                 human_audit → (is_permitted) → issue_permit → END     │
│                 issue_permit → SCADAGatewayAdapter.issue_credential() │
│          ③ record_card(permit_result)                                │
│          ④ finalize_status(PERMITTED|REJECTED, signature_hash?)      │
│      → 成功：fetchTasks() 刷新（该条从列表消失）                       │
│      → 409：fetchTasks() 刷新剔除脏任务 + notice 提示                 │
└──────────────────────────────┬───────────────────────────────────────┘
                               ↓
┌──────────────────────────────────────────────────────────────────────┐
│ ⑧ 查看结果                                                             │
│    plugins/power_grid/cards/PermitResultCard.vue                      │
│      PERMITTED 徽章 / 调度令编号 DISP-YYYYMMDD-XXXXXXXX               │
│      CA 签名前 24 位 + … / 二维码（内容 = permit_no|ca_signature_hash）│
│    刷新页面 → IndexedDB 恢复会话与消息                                │
└──────────────────────────────────────────────────────────────────────────┘
```

### 逐步骤调用链

| # | 位置 | 动作 | 落库 / 副作用 |
|---|---|---|---|
| 1 | `App.vue` onMounted → `core/api/plugin.ts::fetchPluginManifest` | 拉取后端清单（**无鉴权**） | — |
| 2 | `core/plugins/registry.ts::applyManifestEndpoints / applyManifestIdentities` | 用后端下发值覆盖本地默认值 | — |
| 3 | `core/composables/useCurrentUser.ts` → `POST /auth/login` | 换 JWT | — |
| 4 | `localStorage['auth_token']` | 保存令牌（`http.ts` 拦截器自动挂 Bearer） | localStorage |
| 5 | `useWorkbenchStore.hydrateConversations(userId)` | 载入该用户的会话集合 | IndexedDB `conversations:<userId>` |
| 6 | `plugins/power_grid/forms/SubstationApplyForm.vue` → `POST /apply` | 业务提报 | `ai_thread_mappings` + `ai_chat_messages` |
| 7 | `useWorkbenchStore.applyResult(result)` | 三合一收口 | IndexedDB（防抖 1000ms） |
| 8 | `core/api/agent.ts::chatStream` | 流式问答 | `ai_thread_mappings` + `ai_chat_messages` + `ai_execution_traces` |
| 9 | `TaskApprovalPool.vue::fetchTasks` → `GET /tasks` | 待办池 | — |
| 10 | `TaskApprovalPool.vue::openDetail` → `GET /messages` | 详情卡片 | — |
| 11 | `TaskApprovalPool.vue::decide` → `useWorkflowAction.submitAudit` | 提交核签 | `ai_thread_mappings`（CAS +1）+ `ai_chat_messages`（permit_result 卡） |
| 12 | `PermitResultCard.vue` | 展示许可令与二维码 | — |

---

## 3.3 动线三：电力业务插件动线（Power Grid Business Flow）

### 3.3.1 插件如何物理隔离挂载

```
┌──────────────────────── 通用底座（零业务词汇） ────────────────────────┐
│                                                                        │
│  backend/main.py                                                       │
│    ├── load_dotenv(backend/.env)                                       │
│    ├── PluginLoader.load_active()          ← 模块 import 期，fail-fast  │
│    │     └── discover(): 扫描 app/plugins/*/plugin.py                    │
│    │           ├── 无 plugin.py          → debug 日志，跳过              │
│    │           ├── 依赖缺失              → 向上抛出（fail-fast）        │
│    │           ├── 未导出 PLUGIN         → warning，跳过                │
│    │           ├── PLUGIN 类型不符       → PluginContractError         │
│    │           └── manifest.name ≠ 目录名 → PluginContractError        │
│    │     └── 选择生效：ACTIVE_PLUGIN > 唯一插件 > 报错                   │
│    │     └── _seed_identities() → IAMGatewayAdapter.register_user()    │
│    ├── app.include_router(active_plugin.router,                        │
│    │                      prefix=active_plugin.router_prefix)          │
│    └── lifespan:                                                        │
│          graph_factory(saver) → GraphRegistry.register_graph(name, g)  │
│                                                                        │
│  后端 = 端点路径与演示身份的唯一真相源                                 │
│    GET /api/v1/plugin/manifest → { name, version, endpoints, identities }│
└────────────────────────────────────────────────────────────────────────┘
                                    ▲
                    物理隔离边界（24 词黑名单 CI 门禁）
                                    ▼
┌──────────────────── 电力业务插件（app/plugins/power_grid/） ──────────┐
│                                                                        │
│  plugin.py      PluginManifest（name=power_grid, version=1.0.0）       │
│                 ├─ router          = power_dispatch_router             │
│                 ├─ router_prefix   = /api/v1/power-dispatch            │
│                 ├─ graph_factory   = build_dispatch_graph              │
│                 ├─ graph_name      = power_grid                        │
│                 ├─ chat_handler    = power_grid_chat_handler           │
│                 ├─ endpoint_paths  = {tasks,messages,resume,apply}     │
│                 └─ identities      = (applicant_01, dispatcher_lead)   │
│                                                                        │
│  router.py      4 个端点：/apply /tasks /messages /audit                │
│  graph.py       4 节点状态机：safety_check→oms_draft→human_audit→issue │
│  chat.py        RAG 问答处理器                                         │
│  states.py      DispatchState（继承 BaseWorkflowState）                 │
│  constants.py   插件私有常量（角色/状态/卡片类型/端点）                  │
│  adapters/      oms_adapter.py（Mock） / scada_adapter.py（Mock）      │
│  schemas.py     ⚠️ 整文件死代码（无任何 import）                        │
└────────────────────────────────────────────────────────────────────────┘
                                    ▲
                    物理隔离边界（同一道门禁）
                    ▼
┌──────────────────── 前端插件（frontend/src/plugins/power_grid/） ──────┐
│  plugin.ts   PluginDefinition                                         │
│                name=power_grid, version=1.0.0                          │
│                endpoints（本地默认值，后端 manifest 覆盖）              │
│                cards: dispatcher_audit→SafetyDiffCard                  │
│                       permit_result→PermitResultCard                   │
│                       power_grid_citations→CitationsCard               │
│                formComponent: SubstationApplyForm                      │
└────────────────────────────────────────────────────────────────────────┘
```

**隔离机制的三条硬约束**：

| 约束 | 落地方式 |
|---|---|
| 底座代码不出现业务词汇 | [`backend/scripts/check_plugin_isolation.py`](backend/scripts/check_plugin_isolation.py) 扫描 `app/core/`、`app/schemas/a2ui.py`、`app/api/v1/agent.py`、`app/api/v1/plugin.py`、`app/services/acl/`、`frontend/src/core/`；24 词黑名单；`@isolation-exempt` 可豁免；退出码 0/1 |
| 底座不 import 业务模块 | `core/plugin/loader.py` 只 `from app import plugins as plugins_package`（插件容器包），**不引用任何具体业务插件** |
| 端点路径不双向硬编码 | 后端 `manifest.endpoints` → `GET /plugin/manifest` → 前端 `PluginRegistry.applyManifestEndpoints()` 覆盖本地默认值 |

### 3.3.2 `biz_id` 弱引用与防腐层交互

**弱引用设计**：`biz_order_id`（OMS 正式工单号）**不建物理外键**。它只以字符串形式出现在三处：

```
  graph.py :: oms_draft_node
      └─ OMSGatewayAdapter.create_official_order(...) → "OMS-20261112-482913"
              │
              ├─► ① 图状态 state["biz_order_id"]              （LangGraph Checkpointer）
              ├─► ② ai_chat_messages.card_payload->>'biz_order_id'   （JSONB）
              └─► ③ ai_thread_mappings.biz_order_id            （⚠️ 列存在但从不写入）
```

> **为什么是弱引用**：业务单据由**外部系统**（OMS）拥有生命周期与主键语义，AI 中台不拥有它，因此不建外键、不做级联。代价是**一致性全靠应用层维护** —— 而当前代码漏写了第 ③ 处（见第五章 G1）。

**防腐层交互（Anti-Corruption Layer）**：

```
  业务状态机节点                        防腐层边界                        外部系统
  ─────────────                        ──────────                        ─────────
  oms_draft_node                   →   OrderAdapterProtocol            →  真实 OMS
    OMSGatewayAdapter                    .create_official_order(draft,creator_id)
      .create_official_order()   ← Mock 实现，返回 OMS-YYYYMMDD-NNNNNN
      .update_order_status()     ← Mock 实现，只打日志（★ 无人调用）

  issue_permit_node                 →   CredentialAdapterProtocol        →  真实 SCADA
    SCADAGatewayAdapter                   .issue_credential(biz_order_id, reviewer_id)
      .issue_credential()        ← Mock 实现，签发 DISP-YYYYMMDD-XXXXXXXX
                                           + sha256 CA 签名
```

**替换真实系统的操作面**：只需替换 `adapters/oms_adapter.py` / `adapters/scada_adapter.py` 的**类内部实现**，保持 `@staticmethod async` + 同名同参的签名不变 —— 状态机节点、路由、契约 Protocol **均无需改动**。

### 3.3.3 工单 / 调度许可闭环

```
  提报员 (APPLICANT)                调度长 (DISPATCHER)              系统侧落库
  ─────────────────                ───────────────────              ──────────
  POST /apply
    │
    ├─ 建档 ai_thread_mappings
    │   status=WAITING_HUMAN, lock_version=1,
    │   creator_id=applicant_01, creator_role=APPLICANT,
    │   assigned_role=DISPATCHER, creator_dept=运检一班
    │
    ├─ graph.ainvoke
    │   safety_check ── 关键词「接地线」「验电」校验
    │      ├─ 有违规 → END  ─────────────────────────────► status=SAFETY_REJECTED
    │      │                                             is_archived=true
    │      │                                             messages: kind=text
    │      └─ 无违规 ↓
    │   oms_draft  → biz_order_id = OMS-20261112-482913
    │   human_audit → interrupt()  ★ 挂起
    │
    └─ aget_state → snapshot.interrupts 非空
         → messages: kind=card, card_type=dispatcher_audit
         → 出现在 GET /tasks 待办池
                                              │
                                              │ GET /tasks
                                              │ GET /messages?thread_id=
                                              │   → SafetyDiffCard
                                              │
                                              │ 点「核准」
                                              ▼
                          POST /audit {thread_id, lock_version:1, approved:true, opinion}
                            │
                            ├─ require_roles(['DISPATCHER'])  → 否则 403
                            ├─ CAS UPDATE
                            │     lock_version 1 → 2
                            │     operator_id=dispatcher_lead
                            │     audit_opinion=安措完备，准予开工
                            │     rowcount==0 ⇒ 409
                            ├─ graph.ainvoke(Command(resume={is_permitted:true,…}))
                            │     human_audit → issue_permit
                            │       SCADAGatewayAdapter.issue_credential()
                            │         permit_no = DISP-20261112-A98F6FEE
                            │         ca_signature_hash = sha256(
                            │           "DISP-…|OMS-…|dispatcher_lead|APPROVED")
                            │     → END
                            ├─ record_card(permit_result)
                            └─ finalize_status(PERMITTED, signature_hash)
                                  → status=PERMITTED
                                  → messages: card_type=permit_result
                                              │
                                              ▼
                          前端 PermitResultCard：许可令编号 + CA 签名 + 二维码
```

**三条终态路径的差异（对照表）**：

| 路径 | `status` | `lock_version` | `is_archived` | `signature_hash` | `permit_info` | 消息 `kind` / `card_type` | 进入待办池？ |
|---|---|---|---|---|---|---|---|
| 核准 | `PERMITTED` | 1 → **2** | `false` | **有** | 有 | `card` / `permit_result` | 核准后离开 |
| 驳回 | `REJECTED` | 1 → **2** | `false` | **无** | `null` | `card` / `permit_result` | 驳回后离开 |
| 安规否决 | `SAFETY_REJECTED` | **1**（无 CAS） | **true** | 无 | — | **`text`** / `null` | **否**（已归档） |

---

# 第四章 手把手手动端到端测试验证指南（重中之重）

> **本章目标**：让一个**完全没接触过本项目**的人，从空环境开始，照着敲命令，能独立跑通「知识库入库与检索 → 电力工单提报 → 人工核签 → 许可令签发 → SSE 流式问答 → 自动化测试」的全部核心功能，并对每一步给出**可勾选的逐字段期望值**。
>
> **本章所有命令均为「写给读者执行的指令」**，本次编写文档时**没有代为执行**任何会改动数据的步骤（建临时语料、删切片等），以免污染你的工作区。

## 4.0 运行时基线声明（**必读，否则你会误判系统坏了**）

以下是编写本文档时**在本机实际跑过**的结论。**它描述的是"当前这套配置下的正常状态"，不是缺陷。**

| 能力 | 当前状态 | 证据 | 后果 |
|---|---|---|---|
| 聊天 LLM（`ChatOpenAI`） | ✅ **可用** | `resolve_model_name()` 返回实际生效模型；实测一次完整问答返回 207 input / 18 output tokens | 对话链路可完整跑通 |
| 向量服务（`EmbeddingService`） | ⚠️ **已降级为 MD5 伪向量** | `backend/.env` **未配置** `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` ⇒ 回落到 `OPENAI_BASE_URL`（聊天厂商端点），但 `EMBEDDING_MODEL_NAME` 是另一家的向量模型 ⇒ 供应商返回空 data ⇒ openai SDK 抛裸 `ValueError` ⇒ 落进伪向量兜底 | **语义检索必然失效** |
| `ai_knowledge_base` 存量数据 | ⚠️ **是早期真实语义向量**（638 行，同文档内余弦 0.55~0.80） | 用正确向量端点灌入的历史数据 | 库里是"真向量"，但**查询端发的是"伪向量"** ⇒ 两者不在同一表示空间 |

### 由此推出的三条基线断言

1. **`POST /api/v1/knowledge/search` 在默认 `min_similarity=0.5` 下必定返回 `[]`**（实测）。
2. **把 `min_similarity` 调到 `0` 会返回一批"相似度 0.072 ~ 0.082"的噪声命中，且往往命中错误的文档** —— 这是伪向量的指纹（真向量之间的余弦本应在 0.55~0.80）。
3. **场景 B（工单 + 人工审批）不依赖向量服务，可完整跑通** —— 因为安规校验用的是关键词规则，而不是 RAG 召回。

> 📌 **本章场景 A 因此设计成「先诊断、后断言」**：先跑 A.0 探针判定当前是"伪向量模式"还是"真语义模式"，再决定后面哪些断言应该通过、哪些是**预期失败**。
> 📌 **场景 D 想看到 `ui_card` 引文卡，前提是检索非空** —— 在伪向量模式下默认检索恒空，因此场景 D 在当前配置下只能看到 `token` + `done`。这不是 bug。

---

## 4.1 环境前置检查清单

### 4.1.1 运行时基线表

| 依赖 | 本机实测值 | 检查命令 | 通过标准 |
|---|---|---|---|
| Docker | 正常运行 | `docker version` | 有版本号 |
| Docker Compose | v2（`docker compose` 子命令） | `docker compose version` | ≥ 2.x |
| PG 容器 | `power_ai_postgres`，`pgvector/pgvector:pg16`，**healthy** | `docker ps --filter name=power_ai_postgres` | `STATUS` 含 `(healthy)` |
| 端口 5432 | 已映射到宿主机 | `docker port power_ai_postgres` | `0.0.0.0:5432` |
| Python | conda env `power-agent` | 见下方命令 | `python --version` ≥ 3.11 |
| Node.js | 18+ | `node --version` | ≥ v18 |
| npm | 随 Node 附带 | `npm --version` | 有版本号 |
| **宿主机 psql** | ❌ **不存在** | `psql --version` | 不存在是**正常的**，所有 SQL 走 `docker exec` |

### 4.1.2 Python 环境定位（Git Bash 与 PowerShell 的关键差异）

> ⚠️ **Git Bash 里 `conda` 不在 PATH**。本机 conda 装在 `C:\Users\lj\miniconda3`，因此 Git Bash 下要用绝对路径。

**Git Bash：**

```bash
# 新开一个终端先执行（或每次会话都加）
export PATH="/c/Users/lj/miniconda3/envs/power-agent:$PATH"
which python
python --version      # 期望 Python 3.11.x
python -c "import fastapi, langgraph, sqlalchemy, pgvector; print('deps OK')"
```

**PowerShell：**

```powershell
conda activate power-agent
python --version
python -c "import fastapi, langgraph, sqlalchemy, pgvector; print('deps OK')"
```

> 💡 **一条更稳的办法（推荐）**：本项目所有 Python 命令都写成绝对路径形式，避免 PATH 问题：
> ```bash
> PY=/c/Users/lj/miniconda3/envs/power-agent/python.exe
> $PY --version
> ```

### 4.1.3 Windows 中文编码前置

```powershell
chcp 65001
$env:PYTHONIOENCODING="utf-8"
```

```bash
export PYTHONIOENCODING=utf-8
```

> 原因：日志与 JSON 里有大量中文（`安规校验未通过…`、`调度许可令已签发。`），Windows 默认 GBK 控制台会导致乱码。
> 代码侧已做的兜底：`backend/main.py` 与 `backend/conftest.py` 都在 `import psycopg` **之前**切换 `asyncio.WindowsSelectorEventLoopPolicy()`（psycopg 3 在 Proactor 事件循环下不可用）。

### 4.1.4 数据库结构检查

**统一用 `docker exec` 进容器执行 `psql`**（宿主机没有 psql）。为避免在文档里写死数据库账号与库名，统一从 `backend/.env` 读：

**Git Bash：**

```bash
cd <项目根目录>
set -a; . ./backend/.env; set +a     # 仅导出变量，不回显值
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c "\dx"
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c "\dt"
```

**PowerShell：**

```powershell
Set-Location <项目根目录>
$cfg = @{}
Get-Content backend\.env | ForEach-Object {
  if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $cfg[$matches[1]] = $matches[2] }
}
docker exec -i power_ai_postgres psql -U $cfg['DB_USER'] -d $cfg['DB_NAME'] -c "\dx"
docker exec -i power_ai_postgres psql -U $cfg['DB_USER'] -d $cfg['DB_NAME'] -c "\dt"
```

**期望结果**：

| 检查项 | 期望值 |
|---|---|
| `\dx` | `vector` 扩展 **0.8.7**、`uuid-ossp` 扩展 **1.1** |
| `\dt` | **9 张表**：`ai_knowledge_base` / `ai_thread_mappings` / `ai_chat_messages` / `ai_execution_traces` + `checkpoints` / `checkpoint_blobs` / `checkpoint_writes` / `checkpoint_migrations` + `alembic_version` |
| Alembic 版本 | `844a9489b970`（head） |
| 向量列维度 | `embedding vector(1024)` |
| HNSW 索引 | `idx_knowledge_embedding_hnsw` on `embedding` USING `hnsw` (`m=16`, `ef_construction=64`, `vector_cosine_ops`) |

> 📌 **`checkpoint_*` 四张表由应用启动时自动建**（`AsyncPostgresSaver.setup()`），**被 `backend/migrations/env.py::include_object` 显式排除在 Alembic 之外** —— 所以 Alembic 不会管它们，但 `alembic upgrade head` 也不会删它们。

**核对向量列与索引**：

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT column_name, udt_name FROM information_schema.columns WHERE table_name='ai_knowledge_base' AND column_name='embedding';"

docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='ai_knowledge_base';"
```

### 4.1.5 `.env` 必填项校验（**只报键名与状态，绝不回显值**）

**Git Bash：**

```bash
cd backend
for k in DB_USER DB_PASSWORD DB_NAME JWT_SECRET_KEY; do
  if grep -qE "^${k}=.+" .env; then echo "[OK]      $k"; else echo "[MISSING] $k"; fi
done
echo "--- 以下为可选键，缺失会触发降级或默认值 ---"
for k in DB_HOST DB_PORT OPENAI_API_KEY OPENAI_BASE_URL OPENAI_MODEL_NAME \
         EMBEDDING_API_KEY EMBEDDING_BASE_URL EMBEDDING_MODEL_NAME EMBEDDING_DIM \
         ACTIVE_PLUGIN LLM_TIMEOUT LLM_MAX_RETRIES; do
  if grep -qE "^${k}=.+" .env; then echo "[SET]     $k"; else echo "[ABSENT]  $k"; fi
done
```

**PowerShell：**

```powershell
Set-Location backend
$cfg = @{}
Get-Content .env | ForEach-Object {
  if ($_ -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $cfg[$matches[1]] = $matches[2] }
}
'DB_USER','DB_PASSWORD','DB_NAME','JWT_SECRET_KEY' | ForEach-Object {
  if ($cfg.ContainsKey($_) -and $cfg[$_].Trim()) { "[OK]      $_" } else { "[MISSING] $_" }
}
```

**判定表**：

| 键 | 缺失后果 | 缺失是致命的吗 |
|---|---|---|
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `core/database.py` **模块 import 期**就 `RuntimeError` | ❌ **致命** —— 进程根本起不来 |
| `JWT_SECRET_KEY` | 首次签发 Token 时 `RuntimeError`（登录接口 500） | ❌ **致命**（仅对登录功能） |
| `OPENAI_API_KEY` | `build_chat_model()` 返回 `None` → 全部走确定性降级 | 否，但对话质量降级 |
| `OPENAI_BASE_URL` | 走 OpenAI 官方端点 | 否 |
| `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` | **回落到聊天侧配置 ⇒ 供应商错配 ⇒ 伪向量** | 否，但 **RAG 语义能力失效**（见 4.0） |
| `EMBEDDING_MODEL_NAME` | 默认 `doubao-embedding-vision` | 否 |
| `EMBEDDING_DIM` | 默认 `1024`（**必须与表列维度一致**，否则写库报错） | 否，但不要乱改 |
| `ACTIVE_PLUGIN` | 仅一个插件时自动选中；**多个插件且未设 ⇒ 启动即失败** | 视插件数量而定 |
| `LLM_TIMEOUT` / `LLM_MAX_RETRIES` | 默认 30.0 秒 / 2 次 | 否 |

---

## 4.2 服务启动命令

### 4.2.1 数据库容器启动（⚠️ 有一个必踩的坑）

[`docker-compose.yml`](docker-compose.yml) 使用了 `${DB_PASSWORD:?请先在 .env 中配置 DB_PASSWORD 后再启动容器}`：

```yaml
POSTGRES_PASSWORD: ${DB_PASSWORD:?请先在 .env 中配置 DB_PASSWORD 后再启动容器}
```

**Compose 只读取「项目根目录」的 `.env`**，而本项目的 `.env` 在 **`backend/`** 下，**仓库根目录没有 `.env`**。因此：

```bash
# ❌ 裸跑必然失败：required variable DB_PASSWORD is missing a value
docker compose up -d

# ✅ 正确写法（实测 exit 0）
docker compose --env-file backend/.env up -d
```

**PowerShell：**

```powershell
docker compose --env-file backend\.env up -d
```

> 💡 **备选方案**：在**项目根目录**建一个只含 `DB_NAME` / `DB_USER` / `DB_PASSWORD` 三键的 `.env`（根 `.env` 已被 `.gitignore` 覆盖，不会入库），之后 `docker compose up -d` 就能裸跑。

**验证容器**：

```bash
docker compose --env-file backend/.env ps
docker ps --filter name=power_ai_postgres --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"
# 期望：power_ai_postgres   Up ... (healthy)   0.0.0.0:5432->5432/tcp
```

> ⚠️ `docker-compose.yml` 里的 `version: '3.8'` 已被 Compose v2 废弃，会打印一行 `the attribute 'version' is obsolete` 告警 —— **无害，忽略即可**。

### 4.2.2 Alembic 迁移（**必须在 `backend/` 目录下执行**）

```bash
cd backend
alembic upgrade head
alembic current        # 期望：844a9489b970 (head)
```

> 📌 **为什么必须在 `backend/` 下**：`backend/alembic.ini` 用的是 `script_location = %(here)s/migrations`（`%(here)s` = ini 文件所在目录），`migrations/env.py` 又用 `ASYNC_DB_URL` 覆盖连接串并按**绝对路径**加载 `backend/.env` —— 但 `alembic.ini` 本身必须从 `backend/` 目录被找到。

> 🚨 **`alembic downgrade` 会删除 `ai_*` 四张表并丢数据**。本手册任何步骤都不需要 downgrade。

### 4.2.3 后端服务启动

**PowerShell（推荐）：**

```powershell
Set-Location backend
conda activate power-agent
uvicorn main:app --reload --port 8000
```

**Git Bash：**

```bash
cd backend
/c/Users/lj/miniconda3/envs/power-agent/python.exe -m uvicorn main:app --reload --port 8000
```

**启动日志期望（按顺序）**：

```
[插件装载] 生效插件=power_grid v1.0.0 端点=/v1/power-dispatch/tasks, ...
[中枢就绪] 业务插件 power_grid v1.0.0 已挂载（状态图：power_grid） + Checkpointer 连接池就绪
INFO:     Uvicorn running on http://127.0.0.1:8000
```

**就绪探针**（另开一个终端）：

```bash
curl -s http://127.0.0.1:8000/api/v1/health
```

**期望**：

```json
{"code":200,"status":"ok","plugin":"power_grid","graph_ready":true}
```

> 🔑 **`graph_ready: true` 是"后端完全就绪"的一站式断言** —— 它同时意味着：检查点池已打开、4 张 `checkpoint_*` 表已建、状态图已注册进 `GraphRegistry`。若为 `false`，说明 `graph_factory` 未执行（通常是没有可用插件）。

**常见启动失败对照**：

| 报错 | 根因 | 处置 |
|---|---|---|
| `RuntimeError: 缺少必需的环境变量 DB_USER` | `.env` 缺失该键 | 补 `backend/.env`（键名见 4.1.5） |
| `RuntimeError: 缺少必需的环境变量 DB_PASSWORD` | 同上 | 同上 |
| `RuntimeError: 缺少必需的环境变量 DB_NAME` | 同上 | 同上 |
| `PluginContractError: 检测到多个业务插件 …` | 放了多个插件且未设 `ACTIVE_PLUGIN` | 设 `ACTIVE_PLUGIN=power_grid` |
| `PluginContractError: …router_prefix 必须以 /api 开头` | 插件清单契约违规 | 修插件 `constants.py` |
| `RuntimeError: 未找到已注册的工作流图…` | 插件没声明 `graph_factory`，或 `graph_name` 与注册名不符 | 对齐 `POWER_GRAPH_NAME` |
| `Event loop is closed` / psycopg 报错 | Windows Proactor 事件循环 | 代码已处理；请确认跑的是 `backend/main.py` 而不是自己 new 的 loop |

> ⚠️ **`--reload` 的注意事项**：uvicorn 的 reload 由 watchdog 监视当前工作目录。手工测试期间若同时跑 pytest（会写 `.pyc`）或改动文件，**会触发后端反复重启**。因此：**做手工测试时建议去掉 `--reload`**（`uvicorn main:app --port 8000`）；只有在改代码时才用 `--reload`。
>
> 💡 **另一个坑**：本机 `--reload` 实际**不热重载**（依赖变更需手动重启）。改完代码请手动重启后端。

### 4.2.4 前端服务启动

```bash
cd frontend
npm install          # 首次或依赖变更后
npm run dev
```

**期望**：`http://localhost:5173`（Vite 默认端口）。

- [`frontend/vite.config.ts`](frontend/vite.config.ts) 配置了代理：`/api` → `http://127.0.0.1:8000`（`changeOrigin: true`）。前端调用 `/api/v1/...` 因此与后端**同源**，浏览器不涉及跨域。
- **无 `vue-router`**：页面切换靠组件内部状态，不是 URL 路由。
- **无 `pinia`**：状态管理是自建的 `reactive()` 单例。
- **无 `vitest`、无 `test` 脚本**：`package.json` 的 scripts 只有 `dev` / `build` / `preview`。前端**只能手工验证**。

**前端唯一自动化门禁**（每次交付前必须跑）：

```bash
cd frontend
npm run build        # = vue-tsc -b && vite build
```

**期望**：`vue-tsc` 无类型错误（严格模式，禁 `any`），`vite build` 产出 `dist/`。有类型错误会**直接失败退出**。

---

## 4.3 分步剧本

### 4.3.0 通用准备：获取令牌与身份表

**演示身份表**（`app/plugins/power_grid/plugin.py::PLUGIN.identities` 在启动时登记进 Mock IAM；`demo_user` 是 IAM 内置的通用账号）：

| user_id | name | role | dept | 来源 |
|---|---|---|---|---|
| `applicant_01` | 张三 | `APPLICANT` | 运检一班 | 插件清单 |
| `dispatcher_lead` | 王调度长 | `DISPATCHER` | 调度控制中心 | 插件清单 |
| `demo_user` | 演示用户 | `DEFAULT` | （空） | IAM 内置 `MOCK_USERS` |

**获取令牌**（PowerShell 的 `curl` 是 `Invoke-WebRequest` 别名，**必须写 `curl.exe`**）：

```bash
# Git Bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user_id":"applicant_01"}'
```

```powershell
# PowerShell
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{"user_id":"applicant_01"}'
```

**期望响应**：

```json
{"access_token":"<JWT>","token_type":"bearer","user":{"sub":"applicant_01","name":"张三","role":"APPLICANT","dept":"运检一班","iat":...,"exp":...}}
```

**再取一个调度长令牌**，把两个令牌保存到变量（下面所有命令都用 `$TOKEN_APPLICANT` / `$TOKEN_DISPATCHER`）：

**Git Bash：**

```bash
TOKEN_APPLICANT=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"user_id":"applicant_01"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

TOKEN_DISPATCHER=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" -d '{"user_id":"dispatcher_lead"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

echo "applicant token len  : ${#TOKEN_APPLICANT}"
echo "dispatcher token len : ${#TOKEN_DISPATCHER}"
```

**PowerShell：**

```powershell
$applicant  = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/login `
               -ContentType 'application/json' -Body '{"user_id":"applicant_01"}'
$dispatcher = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/auth/login `
               -ContentType 'application/json' -Body '{"user_id":"dispatcher_lead"}'
$TOKEN_APPLICANT  = $applicant.access_token
$TOKEN_DISPATCHER = $dispatcher.access_token
```

> 📌 令牌有效期 **12 小时**（`ACCESS_TOKEN_EXPIRE_HOURS = 12`），过期后调任何受保护端点都返回 **401 `Token 已过期，请重新登录。`**。

### 4.3.1 场景 A · 知识库入库与 RAG 检索

> **本场景的设计前提**：当前配置大概率处于"伪向量模式"（见 4.0）。因此 **A.0 是必做步骤**，它决定后面哪些断言该通过、哪些是**预期失败**。

#### A.0 【必做】向量服务诊断探针

在 `backend/` 下新建一个**临时**脚本 `backend/_probe_embedding.py`（测完删除）：

```python
"""临时诊断脚本：判定向量服务处于「真语义模式」还是「伪向量降级模式」。"""
import asyncio
import math
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from app.core.rag.embeddings import EMBEDDING_DIM, EmbeddingService


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def main() -> None:
    svc = EmbeddingService()
    print("model_name      :", svc.model_name)
    print("base_url        :", svc.base_url)
    print("api_key_set     :", bool(svc.api_key))
    print("EMBEDDING_DIM   :", EMBEDDING_DIM)

    t1 = "接地线装设要求"
    t2 = "验电操作规程"
    v1 = (await svc.get_embeddings([t1]))[0]
    v2 = (await svc.get_embeddings([t2]))[0]

    pseudo = EmbeddingService._pseudo_embedding(t1)
    degraded = all(abs(a - b) < 1e-6 for a, b in zip(v1, pseudo))

    print("DEGRADED_TO_PSEUDO:", degraded)
    print("cos(self)       :", round(cos(v1, v1), 6))
    print("cos(cross)      :", round(cos(v1, v2), 6))
    print("vector_len      :", len(v1))

    if degraded:
        print("\n==> 判定：伪向量降级模式")
        print("    后续 A.4 的语义断言【预期失败】；A.3 应命中噪声。")
        print("    修复路径见 A.6。")
    else:
        print("\n==> 判定：真语义模式")
        print("    后续 A.4 的语义断言【应当通过】。")


if __name__ == "__main__":
    asyncio.run(main())
```

**运行**：

```bash
cd backend
python _probe_embedding.py
```

**判定表**：

| `DEGRADED_TO_PSEUDO` | `cos(self)` | `cos(cross)` | 模式 | 后续断言 |
|---|---|---|---|---|
| `True` | `1.0` | `≈ 0`（完全正交） | **伪向量降级** | A.4 **预期失败**；A.3 命中噪声 |
| `False` | `> 0.9` | `> 0.6`（语义相近） | **真语义** | A.4 **应当通过** |

> 📌 **本机实测 = 伪向量降级模式**（`cos(cross) ≈ 0`，两段毫不相关的安规文本被算成完全垂直）。这就是 `EMBEDDING_BATCH_SIZE=8` 那条注释所说的"不同表示空间"现象。

#### A.1 准备临时语料

> ⚠️ **注意**：临时语料**不要放在 `backend/tests/`**（那里被 gitignore，但也不适合放语料）；放在 `backend/plugins/power_grid/documents/` 下**会被 git 跟踪**，测完必须删除（见 A.7）。

在 `backend/plugins/power_grid/documents/_smoke_test.md` 新建：

```markdown
# 检修安规冒烟测试语料

## 3.0米安全距离
检修现场作业人员与带电设备之间应保持不小于 3.0米 的安全距离，
不足时应加装绝缘隔板并设专人监护。

## 验电要求
装设接地线前必须先验电确认无电压，验电应使用合格且电压等级相符的验电器。

## 接地线装设
停电检修可能来电的各端均应装设接地线，接地线应装设在检修设备导电部分的规定地点。
```

**期望**：3 个二级标题 ⇒ 解析器产出 3 个 section ⇒ 分块器按 500/50 切成 **3 条**（每节都很短，不会被再切）。

#### A.2 入库

```bash
cd backend
python scripts/rag_ingest_file.py \
  --files plugins/power_grid/documents/_smoke_test.md \
  --biz-tag power_grid \
  --doc-code SMOKE-TEST-001 \
  --doc-version v1.0
```

**期望输出**：

```
文件 plugins/power_grid/documents/_smoke_test.md：新插入切片 3 条

========== RAG 文件入库汇总 ==========
处理文件数 : 1
切片插入数 : 3
规程版本   : v1.0
======================================
```

**幂等复测**（**再跑一遍同样的命令**）：

```bash
python scripts/rag_ingest_file.py \
  --files plugins/power_grid/documents/_smoke_test.md \
  --biz-tag power_grid \
  --doc-code SMOKE-TEST-001 \
  --doc-version v1.0
```

**期望**：这次输出 **`新插入切片 0 条`** —— 去重键是 `(doc_code, content.strip())`，命中已有切片即跳过。

**回读断言**：

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT doc_code, biz_tag, section_title, is_active, doc_version, length(content) AS len
   FROM ai_knowledge_base WHERE doc_code='SMOKE-TEST-001' ORDER BY chunk_index;"
```

> ⚠️ `ai_knowledge_base` **没有 `chunk_index` 列**（切片序号只在 `DocumentChunk` 对象上，入库时不落库）。上面的 SQL 请改用 `ORDER BY created_at`：

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT doc_code, biz_tag, section_title, is_active, doc_version, length(content) AS len
   FROM ai_knowledge_base WHERE doc_code='SMOKE-TEST-001' ORDER BY created_at;"
```

**期望**：

| doc_code | biz_tag | is_active | doc_version | 行数 |
|---|---|---|---|---|
| `SMOKE-TEST-001` | `power_grid` | `t` | `v1.0` | **3** |

**勾选清单**：
- [ ] 入库输出 `新插入切片 3 条`
- [ ] 二次运行输出 `新插入切片 0 条`
- [ ] DB 回读恰好 3 行，`is_active=t`，`doc_version=v1.0`

#### A.3 检索 API 验证（四步）

**① 匿名访问 → 401**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/v1/knowledge/search \
  -H "Content-Type: application/json" -d '{"query":"接地线"}'
```

**期望**：`401`

**② 默认阈值（`min_similarity=0.5`）→ 本机实测返回 `[]`**

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge/search \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -d '{"query":"检修现场与带电设备的安全距离要求是多少","biz_tag":"power_grid"}'
```

**期望**：`[]`（伪向量模式下的**预期结果**，不是 bug）。

**③ 阈值降到 0 → 返回噪声命中**

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge/search \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -d '{"query":"检修现场与带电设备的安全距离要求是多少","biz_tag":"power_grid","top_k":5,"min_similarity":0}'
```

**期望（伪向量模式）**：返回若干条，`similarity` 落在 **0.07 ~ 0.08** 区间，且**命中的往往不是 `SMOKE-TEST-001`** —— 因为伪向量空间与库里存量真向量空间正交，谁的余弦略大于 0 就命中谁，纯属噪声。

> 📌 **对比真语义模式**：同样这条 query 应该命中 `SMOKE-TEST-001` 的「3.0米安全距离」那条，且 `similarity ≥ 0.6`。

**④ 真伪对照实验（证明"同一张表里两种向量空间并存"）**

先用 DB 取出 `SMOKE-TEST-001` 的**原文**，再用**完全相同的原文**当 query 打检索接口：

```bash
CONTENT=$(docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -t -A \
  -c "SELECT content FROM ai_knowledge_base WHERE doc_code='SMOKE-TEST-001' ORDER BY created_at LIMIT 1;")

curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge/search \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -d "$(python -c "import json,sys;print(json.dumps({'query':sys.argv[1],'doc_code':'SMOKE-TEST-001','top_k':3,'min_similarity':0}))" "$CONTENT")"
```

**期望（伪向量模式）**：该条 `similarity ≈ 1.000000` —— 因为伪向量是**内容的确定性函数**，同一段文本必然得到同一向量，余弦恒为 1。

再对**存量真向量行**做同样的事（取一条 `doc_code != 'SMOKE-TEST-001'` 的内容当 query）：

**期望（伪向量模式）**：相似度 **≈ -0.06（接近 0 甚至为负）** —— 伪向量与真向量**近乎垂直**。

> 🔑 这两条对照**同时成立**，就是"同一张 `ai_knowledge_base` 表里并存两种互不兼容的向量空间"的直接证据。

**勾选清单**：
- [ ] 匿名 → `401`
- [ ] 默认阈值 → `[]`（伪向量模式下预期）
- [ ] 阈值 0 → 有返回，相似度 ~0.07~0.08，且命中文档不正确
- [ ] 真伪对照：伪向量行 ≈ 1.0，真向量行 ≈ 0（近乎垂直）

#### A.4 语义断言（**仅在 A.0 判定为"真语义模式"时才应通过**）

| 断言 | 期望值 |
|---|---|
| 命中的 `doc_code` | `SMOKE-TEST-001` |
| 命中的 `content` | 含 `3.0米` |
| `similarity` | `≥ 0.6` |

**伪向量模式下这三条全部不成立 —— 属预期失败，不是代码缺陷。**

#### A.5 通用问答 `/knowledge/ask`

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge/ask \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -d '{"query":"装设接地线前必须先做什么","biz_tag":"power_grid"}'
```

**期望（伪向量模式）**：

```json
{"question":"装设接地线前必须先做什么","answer":"知识库中暂未检索到与该问题直接相关的规程依据，请核实问题或联系管理员确认。","citations":[]}
```

**期望（真语义模式）** —— 三种合法形态之一：

| 形态 | `answer` 特征 | `citations` |
|---|---|---|
| LLM 生成 | 自然语言，且**引用了条目出处**（因系统提示要求标注出处） | 非空 |
| 确定性降级 | 以 `依据规程要求，相关条款如下：` **开头**，随后逐条列出 `【doc_code】` + 原文 | 非空 |
| 检索为空 | `知识库中暂未检索到…` | `[]` |

> 📌 **降级形态什么时候出现**：`qa_llm` 是**模块级**构造的（`api/v1/knowledge.py:24`）。未配 `OPENAI_API_KEY` 时它为 `None` → 走 `_build_degraded_answer`；配了但调用超时/限流 → `except Exception` 也走降级。**`citations` 始终完整回填**，这是该端点的契约。

#### A.6 修复路径（把语义能力真正打开）

**第 1 步：在 `backend/.env` 补齐向量专用配置**（键名如下，值填你所用向量服务商的端点与密钥）：

```
EMBEDDING_API_KEY=<向量服务商的 Key>
EMBEDDING_BASE_URL=<向量服务商的 embeddings 端点>
EMBEDDING_MODEL_NAME=<与该端点匹配的向量模型名>
```

> ⚠️ **关键**：这三项必须**指向同一个供应商**。当前的问题是「端点来自 A 商、模型名来自 B 商」⇒ 供应商返回空 data ⇒ SDK 抛 `ValueError` ⇒ 静默降级。

**第 2 步：重启后端**（`EmbeddingService.__init__` 在**实例化时**读环境变量，不重启不生效）：

```bash
# 停掉旧进程后重新启动
uvicorn main:app --port 8000
```

**第 3 步：重跑 A.0 探针** → 期望 `DEGRADED_TO_PSEUDO: False`、`cos(cross) > 0.6`。

**第 4 步：重新入库**（**存量真向量必须与新查询端同源**，否则库里仍是混合空间）：

```bash
# ① 用 --overwrite 软废止旧切片（保留可追溯）
python scripts/rag_ingest_file.py \
  --files plugins/power_grid/documents/_smoke_test.md \
  --biz-tag power_grid --doc-code SMOKE-TEST-001 --doc-version v1.0 --overwrite

# ② 更彻底：把存量 638 行也重新灌一遍（见 A.7 的清理 SQL）
```

**第 5 步：重跑 A.3 ② / A.4** → 这次默认阈值下应当能命中 `SMOKE-TEST-001`。

#### A.7 清理（**测完必须做**）

```bash
# ① 删除冒烟切片（软删即可，不物理删）
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "UPDATE ai_knowledge_base SET is_active=false WHERE doc_code='SMOKE-TEST-001';"

# ② 删除临时语料文件
rm backend/plugins/power_grid/documents/_smoke_test.md
# PowerShell:
# Remove-Item backend\plugins\power_grid\documents\_smoke_test.md

# ③ 删除临时探针脚本
rm backend/_probe_embedding.py
```

```bash
# ④ 确认 git 工作区干净（临时语料已被 git 跟踪，必须删掉）
git status --porcelain
```

**期望**：`git status --porcelain` 里**不应出现** `_smoke_test.md`。

---

### 4.3.2 场景 B · 电力调度工单与人工审批流

> **本场景不依赖向量服务**（安规校验用关键词规则），因此在当前配置下**可以完整跑通**。这是验证「通用底座 + 插件」整条链路的**主战场**。

#### B.1 就绪断言

```bash
curl -s http://127.0.0.1:8000/api/v1/health
```

**期望**：`"graph_ready":true`、`"plugin":"power_grid"`。

#### B.2 提报（安措完整 ⇒ 挂起等待核签）

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/power-dispatch/apply \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "manual_test_s1",
    "substation": "城东110kV变电站",
    "voltage_level": "110kV",
    "operation_task": "2号主变高压侧开关检修",
    "safety_measures": ["停电并验电", "挂设接地线", "悬挂禁止合闸标示牌"]
  }'
```

**期望响应**：

```json
{
  "thread_id": "manual_test_s1_<12位十六进制>",
  "status": "WAITING_HUMAN",
  "interrupted": true,
  "card": {
    "card_type": "dispatcher_audit",
    "thread_id": "manual_test_s1_<12位十六进制>",
    "biz_order_id": "OMS-YYYYMMDD-NNNNNN",
    "substation": "城东110kV变电站",
    "voltage_level": "110kV",
    "operation_task": "2号主变高压侧开关检修",
    "violations": [],
    "lock_version": 1
  }
}
```

**逐字段断言**：

| 字段 | 期望 |
|---|---|
| `status` | `WAITING_HUMAN` |
| `interrupted` | `true` |
| `card.card_type` | `dispatcher_audit` |
| `card.biz_order_id` | 形如 `OMS-YYYYMMDD-NNNNNN`（`YYYYMMDD` = 今天日期，`NNNNNN` = 6 位数字） |
| `card.violations` | `[]`（安措含「接地线」「验电」两个关键词 ⇒ 无违规） |
| `card.lock_version` | `1` |
| 响应中**没有** `message` 字段 | ✅（只有安规否决分支才有） |

> 📌 **`thread_id` 生成规则**：`f"{session_id}_{uuid4().hex[:12]}"` —— 每次提报都产生**新** thread_id，**不会复用**。请把返回的 `thread_id` 记下来，后面每一步都要用。
>
> 📌 **响应里没有 `retry_payload`**：重试载荷只写在 **DB 的 `ai_chat_messages.retry_payload`** 里（`{"thread_id": ..., "lock_version": 1}`），前端从卡片历史里取。

**DB 回读断言**：

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT thread_id, status, lock_version, is_archived, creator_id, creator_role,
          assigned_role, creator_dept, biz_order_id, current_node
   FROM ai_thread_mappings WHERE thread_id LIKE 'manual_test_s1_%' ORDER BY created_at DESC;"
```

**期望**：

| 列 | 期望 | 说明 |
|---|---|---|
| `status` | `WAITING_HUMAN` | |
| `lock_version` | `1` | 建档时写入 |
| `is_archived` | `f` | |
| `creator_id` | `applicant_01` | |
| `creator_role` | `APPLICANT` | |
| `assigned_role` | `DISPATCHER` | |
| `creator_dept` | `运检一班` | 来自 JWT 的 `dept` |
| **`biz_order_id`** | **`NULL`** | ⚠️ **预期**：该列当前从不写入（真实 OMS 单号只在 `card_payload` 与图状态里） |
| **`current_node`** | **`NULL`** | ⚠️ **预期**：状态机指针当前从不回写 |

**消息表断言**：

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT role, kind, card_type, retry_payload FROM ai_chat_messages
   WHERE thread_id LIKE 'manual_test_s1_%' ORDER BY created_at;"
```

**期望**：**恰好 1 行**，且 `role=assistant`、`kind=card`、`card_type=dispatcher_audit`、`retry_payload` = `{"thread_id": "...", "lock_version": 1}`。

#### B.3 待办池

**调度长视角（应有数据）**：

```bash
curl -s http://127.0.0.1:8000/api/v1/power-dispatch/tasks \
  -H "Authorization: Bearer $TOKEN_DISPATCHER"
```

**期望**：`{"total": N, "reviewer_id": "dispatcher_lead", "items": [...]}`，其中 `N ≥ 1` 且包含刚才的 `thread_id`。

**提报员视角（应为空，但**不是** 403）**：

```bash
curl -s http://127.0.0.1:8000/api/v1/power-dispatch/tasks \
  -H "Authorization: Bearer $TOKEN_APPLICANT"
```

**期望**：`{"total": 0, "reviewer_id": "applicant_01", "items": []}`，HTTP **200**。

> 📌 **这是设计如此，不是 bug**：`router.py::list_tasks` 对非 `DISPATCHER` 角色"允许访问，安全返回空列表，不抛 403"。源码注释写明了原因 —— 避免前端因角色差异直接崩掉。

**无令牌 → 401**：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/power-dispatch/tasks
```

**期望**：`401`

#### B.4 核准（签发调度许可令）

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/power-dispatch/audit \
  -H "Authorization: Bearer $TOKEN_DISPATCHER" \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"<上一步的 thread_id>","lock_version":1,"approved":true,"opinion":"安措完备，准予开工"}'
```

**期望响应**：

```json
{
  "thread_id": "<thread_id>",
  "status": "PERMITTED",
  "permit_info": {
    "permit_no": "DISP-YYYYMMDD-XXXXXXXX",
    "status": "PERMITTED",
    "ca_signature_hash": "<64位十六进制>",
    "issued_at": "<ISO 时间>"
  }
}
```

**逐字段断言**：

| 字段 | 期望 |
|---|---|
| `status` | `PERMITTED` |
| `permit_info.permit_no` | `DISP-` + `YYYYMMDD` + `-` + **8 位大写十六进制** |
| `permit_info.status` | `PERMITTED` |
| `permit_info.ca_signature_hash` | **64 位小写十六进制**（SHA-256） |

**独立复算 CA 签名（证明签名可验证）**：

签名口径是 `sha256("permit_no|biz_order_id|reviewer_id|APPROVED")`。在 PowerShell 里复算：

```powershell
$permit  = "<permit_no>"
$bizId   = "<card.biz_order_id>"
$reviewer= "dispatcher_lead"
$expected = (Get-FileHash -InputStream ([System.IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes("$permit|$bizId|$reviewer|APPROVED"))) -Algorithm SHA256).Hash.ToLower()
"expected = $expected"
"actual   = <ca_signature_hash>"
```

**期望**：`expected` 与 `actual` **完全一致**。

```bash
# Git Bash 复算
printf '%s' "<permit_no>|<biz_order_id>|dispatcher_lead|APPROVED" | sha256sum
```

**DB 回读断言**：

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT status, lock_version, operator_id, audit_opinion, signature_hash, is_archived
   FROM ai_thread_mappings WHERE thread_id='<thread_id>';"
```

**期望**：

| 列 | 期望 |
|---|---|
| `status` | `PERMITTED` |
| **`lock_version`** | **`2`**（CAS 抢占 +1） |
| `operator_id` | `dispatcher_lead` |
| `audit_opinion` | `安措完备，准予开工` |
| `signature_hash` | 与 `permit_info.ca_signature_hash` **一致** |
| `is_archived` | `f`（**终态不归档** —— 只有安规否决才归档） |

**消息表断言**：应变为 **2 行** —— 第 2 行 `kind=card`、`card_type=permit_result`、`content=调度许可令已签发。`

#### B.5 CAS 冲突重放（**乐观锁核心验证**）

**原封不动重发 B.4 的请求**：

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/v1/power-dispatch/audit \
  -H "Authorization: Bearer $TOKEN_DISPATCHER" \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"<同一个 thread_id>","lock_version":1,"approved":true,"opinion":"重复提交"}'
```

**期望**：**HTTP 409**，响应体：

```json
{"detail":"任务已被其他操作人处理或版本已失效"}
```

**为什么会 409（双重失配）**：CAS UPDATE 的 WHERE 条件同时要求 `lock_version = 1` **且** `status = 'WAITING_HUMAN'`。此刻库里 `lock_version` 已是 `2`、`status` 已是 `PERMITTED` ⇒ `rowcount == 0` ⇒ 底座抛 409。

> 🔑 **这是本系统防重复审批的核心机制**。两个调度长同时点「核准」时，只有一个能成功，另一个拿到 409。

#### B.6 驳回分支

**重新提报一单**（拿到新的 `thread_id`），然后：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/power-dispatch/audit \
  -H "Authorization: Bearer $TOKEN_DISPATCHER" \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"<新 thread_id>","lock_version":1,"approved":false,"opinion":"安措不完整，退回整改"}'
```

**期望响应**：

```json
{"thread_id":"<新 thread_id>","status":"REJECTED","permit_info":null}
```

**三个独有断言**：

| 断言 | 期望 | 根因 |
|---|---|---|
| `permit_info` | **`null`** | `route_after_audit` 走 `END`，**不经过 `issue_permit` 节点** ⇒ 不会调 SCADA |
| `signature_hash`（DB） | **`NULL`（不写）** | `permit_info` 为空 ⇒ `signature_hash = None` ⇒ `finalize_status` 走「不带签名」分支 |
| 消息 `content` | `调度长已驳回本次检修申请。` | `router.py` 的三元表达式 |

**DB 断言**：

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT status, lock_version, signature_hash FROM ai_thread_mappings WHERE thread_id='<新 thread_id>';"
```

**期望**：`status=REJECTED`、`lock_version=2`、`signature_hash=NULL`。

#### B.7 安规否决分支（`SAFETY_REJECTED`）

**提报时安措故意漏掉「接地线」和「验电」**：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/power-dispatch/apply \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "manual_test_s2",
    "substation": "城西220kV变电站",
    "voltage_level": "220kV",
    "operation_task": "母线间隔刀闸检修",
    "safety_measures": ["悬挂禁止合闸标示牌"]
  }'
```

**期望响应**：

```json
{
  "thread_id": "manual_test_s2_<12位十六进制>",
  "status": "SAFETY_REJECTED",
  "interrupted": false,
  "message": "安规校验未通过，检修申请已自动否决，不进入调度长审批池。现场安措未明确“挂设接地线”，依据安规，停电检修可能来电各端必须挂设接地线。；现场安措未明确“验电”，依据安规，装设接地线前必须先验电确认无电压。",
  "card": {}
}
```

**逐字段断言**：

| 字段 | 期望 |
|---|---|
| `status` | `SAFETY_REJECTED` |
| `interrupted` | **`false`**（图直接 END，没挂起） |
| `card` | **`{}`**（空对象，不是 `null`） |
| `message` | 以 `安规校验未通过，检修申请已自动否决，不进入调度长审批池。` 开头，后接两条违规（以 `；` 分隔） |

**两条违规文案（固定字符串）**：

1. `现场安措未明确"挂设接地线"，依据安规，停电检修可能来电各端必须挂设接地线。`
2. `现场安措未明确"验电"，依据安规，装设接地线前必须先验电确认无电压。`

**DB 断言**：

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT status, lock_version, is_archived, archived_at
   FROM ai_thread_mappings WHERE thread_id LIKE 'manual_test_s2_%' ORDER BY created_at DESC;"
```

**期望**：

| 列 | 期望 | 说明 |
|---|---|---|
| `status` | `SAFETY_REJECTED` | |
| **`lock_version`** | **`1`（不递增）** | ⚠️ 这条路径**没有 CAS**，因为压根没人核签 |
| **`is_archived`** | **`t`** | 流程终止即归档，避免滞留在审批池 |
| `archived_at` | 非 NULL | |

**消息表断言**：**恰好 1 行**，且 **`kind='text'`（不是 card）**、`card_type IS NULL`、`content` 以 `安规校验未通过…` 开头。

**待办池断言**：`GET /tasks` 的 `total` **不因这单增加**（已归档 + 非 `WAITING_HUMAN`）。

#### B.8 越权调用（角色门禁）

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/api/v1/power-dispatch/audit \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"<任意 thread_id>","lock_version":1,"approved":true,"opinion":"越权尝试"}'
```

**期望**：**HTTP 403**，响应体 `{"detail":"权限不足，禁止访问该资源。"}`。

**并且**：DB 中该 `thread_id` 的 `lock_version` / `status` / `operator_id` **全部不变**（403 发生在依赖注入阶段，请求根本没进业务逻辑）。

#### B.9 消息快照

```bash
curl -s "http://127.0.0.1:8000/api/v1/power-dispatch/messages?thread_id=<thread_id>" \
  -H "Authorization: Bearer $TOKEN_DISPATCHER"
```

**期望**：

```json
{
  "thread_id": "<thread_id>",
  "requester_id": "dispatcher_lead",
  "items": [
    {"id":"...","thread_id":"...","role":"assistant","kind":"card",
     "content":"检修申请已提交，等待调度长核签。","card_type":"dispatcher_audit",
     "card_payload":{...},"retry_payload":{"thread_id":"...","lock_version":1},
     "created_at":"2026-11-12T03:21:45.123456+00:00"},
    {"id":"...","role":"assistant","kind":"card","content":"调度许可令已签发。",
     "card_type":"permit_result","card_payload":{...},"retry_payload":null,
     "created_at":"..."}
  ]
}
```

**断言**：
- `items` 按 `created_at` **升序**；
- `created_at` 是 **ISO 8601 字符串**（不是时间戳数字）；
- 不存在的 `thread_id` → **200** + `{"items": []}`（**不是 404**）。

#### B.10 前端 UI 观察点（14 步）

**前置**：后端 + 前端都已启动，浏览器打开 `http://localhost:5173`。

| # | 操作 | 期望观察 |
|---|---|---|
| 1 | 打开页面 | Header 身份下拉有两项（张三 / 王调度长）；右上角 SSE 状态灯为 **`Idle`（灰色）** —— **不代表后端离线**，只表示"当前没有进行中的对话流" |
| 2 | 切换身份到「张三」 | 自动调用 `POST /auth/login`，`localStorage['auth_token']` 被写入；左栏加载 `conversations:applicant_01` |
| 3 | 点「📋 快速填报」 | 右栏抽屉展开，露出 `SubstationApplyForm`（变电站 / 电压等级 / 作业内容 + **3 个安措复选框，默认勾选前两个**） |
| 4 | 填表并提交 | 中栏出现 **`dispatcher_audit` 卡片**（含站点、电压、作业内容、违规项、Lock 版本） |
| 5 | 观察卡片按钮 | **提报员视角没有「核准 / 驳回」按钮**（`canAudit` 依据 `hasAnyRole('DISPATCHER')`）—— 只读 |
| 6 | 观察左栏 | 新会话条目出现，徽章 `WAITING_HUMAN`，显示 `Lock: v1` |
| 7 | 取消勾选安措复选框后再次提交 | 中栏出现**纯文本消息**（不是卡片），徽章 `SAFETY_REJECTED` |
| 8 | 切换身份到「王调度长」 | 身份切换后左栏换成 `conversations:dispatcher_lead` 的集合 |
| 9 | 切到「待办审批池」Tab | 列表出现待审工单（含刚才那单） |
| 10 | 点开某条待办 | 卡片下方出现该线程的消息历史（`SafetyDiffCard` 渲染安措差异） |
| 11 | 详情底部 | 出现 **「核准」（绿）** / **「驳回」（灰）** 两个按钮 |
| 12 | 点「核准」 | 该条**从待办列表消失**（后端 `status` 已变 `PERMITTED`，不再满足 `WAITING_HUMAN` 过滤条件）；中栏出现 `permit_result` 卡片 |
| 13 | 观察 `permit_result` 卡片 | `PERMITTED` 徽章 + 调度令编号 `DISP-…` + CA 签名前 24 位 + **二维码**（内容 = `permit_no\|ca_signature_hash`） |
| 14 | **刷新浏览器** | 会话与消息**从 IndexedDB 恢复**（`session:<sessionId>` / `conversations:<userId>`）；右栏「运行追踪」面板恒显示**「暂无数据」**（占位，尚未接 `ai_execution_traces`） |

**补充观察点**：
- 打开浏览器 **Console**：应**无插件版本偏斜告警**。若前后端 `plugin.version` 不一致，页面顶部会出现**黄色提示条**且 Console 有 `warn`（后端 `manifest.version` 与前端 `plugin.ts` 里的 `POWER_PLUGIN_VERSION` 比对）。
- 打开 **Network** 面板：SSE 请求的 `Content-Type` 应为 `text/event-stream`；后端已设 `X-Accel-Buffering: no`。
- **断网重连验证**：对话流进行中拔网线 / 停后端 ⇒ 状态灯应变为 **`reconnecting`**（琥珀）→ 超过 3 次 ⇒ **`offline`**（红）。

---

### 4.3.3 场景 C · 自动化测试脚本一键跑通

> **全部命令在 `backend/` 目录、`power-agent` 环境下执行。**

#### C.0 三个全局前提（不读会踩坑）

| # | 前提 | 后果 |
|---|---|---|
| 1 | **`backend/tests/` 整个目录被 `.gitignore`**（`backend/tests/*` + `!backend/tests/.gitkeep`） | **新克隆的机器上该目录是空的**，12 个测试文件全都不存在 ⇒ `pytest` 会报 `no tests ran` |
| 2 | **`asyncio_mode=strict`**（[`backend/pytest.ini`](backend/pytest.ini)） | 异步用例**必须显式**标 `@pytest.mark.asyncio`，否则**静默不执行**（不报错！只是不跑） |
| 3 | 事件循环为**会话级**（`asyncio_default_fixture_loop_scope` / `asyncio_default_test_loop_scope` 均为 `session`） | 与生产的单进程单循环语义一致；fixture 与用例共享同一循环 |

#### C.1 分批执行与预期

```bash
cd backend
pytest -q -p no:cacheprovider --collect-only
```

**期望**：**6 个模块 / 16 个用例**。

| 命令 | 收集 | 预期结果 | 依赖与说明 |
|---|---|---|---|
| `pytest -q tests/test_acl.py` | 3 | ✅ **3 passed** | **纯 Mock，无外部依赖**。校验 JWT claims 与 12h 有效期、OMS 单号正则、SCADA 许可令正则 + **独立复算 sha256** |
| `pytest -q tests/test_ai_schema.py` | 3 | ✅ **3 passed** | **真实 PG**。校验唯一约束、CAS 更新、JSONB + `<=>` 余弦、HNSW DDL |
| `pytest -q tests/test_dispatch_workflow.py` | 3 | ✅ **3 passed** | **真实 PG** + 手写 bootstrap（**不走 FastAPI lifespan**，自行注册图）+ `httpx.ASGITransport` 在进程内驱动 FastAPI |
| `pytest -q tests/test_pending_pool_filter.py` | 3 | ⚠️ **3 passed（脆弱）** | **真实 PG**。校验待办池的归档过滤；⚠️ 其中 `test_pool_count_unchanged` **硬编码断言 `total == 2`** |
| `pytest -q tests/test_rag2.py` | 1 | ⏭️ **1 skipped** | **真实 PG**。向量降级时该用例**主动 `pytest.skip`**（这正是设计意图） |
| `pytest -q tests/test_rag_api.py` | 3 | ✅ **3 passed** | **真实 PG**。用 `min_similarity=0.0` 适配伪向量 |
| **`pytest -q`（全量）** | **16** | ✅ **15 passed, 1 skipped** | 真实 PG |

**全量执行**：

```bash
cd backend
pytest -q -p no:cacheprovider
```

**期望结尾**：

```
15 passed, 1 skipped in XX.XXs
```

#### C.2 被排除的两个文件

[`backend/conftest.py`](backend/conftest.py) 里有：

```python
collect_ignore = [
    "tests/test_dualmode_graph.py",
    "tests/test_postgres_checkpoint_flow.py",
]
```

**原因**：这两个历史脚本都 import 了插件化重构时**已被整体删除的旧图模块**（旧包路径见第五章「文档漂移专节」）。不排除的话，pytest 会在**收集期**抛 `ImportError`，污染整轮收集。

> 📌 **想确认它们确实失效**，可以显式跑一次看报错（**预期报错，不是新 bug**）：
> ```bash
> pytest -q tests/test_dualmode_graph.py
> # 收集期 ModuleNotFoundError（缺少插件化重构时已删除的旧包）
> ```

#### C.3 三个压力 / 手工脚本（**默认不会被 pytest 收集**）

> 🔑 **事实澄清**：`backend/pytest.ini` **没有覆盖 `python_files`**，所以 pytest 用默认值 `test_*.py` / `*_test.py`。`stress_*.py` 与 `verify_cas_manual.py` **不匹配默认规则 ⇒ 裸跑 `pytest` 不会被收集**（这就是默认 `pytest` 是"干净"的原因）。
> **但显式指定路径后，它们就会跑，并暴露问题。**

**① `stress_cas_concurrency.py` —— ❌ 预期失败（脚本本身过期）**

```bash
pytest -q tests/stress_cas_concurrency.py
```

**预期**：**FAIL**。原因：脚本构造的请求体里发的是 `"is_permitted": True`，而线上 `AuditRequest` 要求的字段名是 **`approved`** ⇒ 全部请求返回 **422** ⇒ 脚本取 `success[0]` ⇒ **IndexError** 收尾。

> ⚠️ 这是**脚本过期**，不是线上接口坏了。线上契约见 `router.py::AuditRequest`：`{thread_id, lock_version, approved, opinion}`。修复方向见第六章 P1。

**② `verify_cas_manual.py` —— ❌ 预期失败（导入名不存在）**

```bash
pytest -q tests/verify_cas_manual.py
```

**预期**：**收集期 ERROR / Interrupted**。原因：脚本里 `from app.core.database import checkpointer_pool` —— 该名字**不存在**；实际导出的是 **`checkpointer_manager`**（`CheckpointerManager` 实例）。

**③ `stress_pool_exhaustion.py` —— ✅ 预期通过（双池隔离验证）**

```bash
pytest -q -s tests/stress_pool_exhaustion.py
```

> ⚠️ **`-s` 必须加** —— 这个脚本靠 `print` 输出结论。

**期望**：**1 passed**，且 stdout 出现：

```
POOL_PHYSICAL_ISOLATION_OK
```

**它验证什么**：后台并发驱动状态机（8×3）同时前台发起 80 个并发 `/tasks` 请求 —— 若业务池与检查点池**没有物理隔离**，检查点写入会因连接耗尽而失败。输出 `POOL_PHYSICAL_ISOLATION_OK` 即证明双池隔离生效。

#### C.4 两个独立脚本（**不是 pytest，必须用 `-m` 运行**）

```bash
cd backend
python -m tests.test_db_init
```

> ⚠️ **必须用 `-m`**：该脚本的事件循环策略切换写在 `if __name__ == "__main__":` 守卫内部，直接 `python tests/test_db_init.py` 不会走到那里。

```bash
python -m tests.test_core_graph
```

> 🚨 **该脚本是历史遗留，与线上完全脱节**：它用的是旧的状态定义、旧的中断方式、以及线上根本不存在的电压定级逻辑。**它的输出不能作为验收依据**，跑它只为确认"老脚本还能跑"。

**插件隔离门禁（CI 用）**：

```bash
python scripts/check_plugin_isolation.py
echo "exit code = $?"
```

**期望**：**exit code = 0**（扫描底座目录 + 前端 `core/`，24 条业务词汇黑名单，命中的行需带 `@isolation-exempt` 豁免标记）。

> 📌 这个脚本**建议纳入 CI** —— 它是"通用底座不含业务词汇"这条架构约束的唯一自动化守卫（见第六章 P2）。

#### C.5 执行顺序规定（**顺序依赖型活雷**）

`tests/test_pending_pool_filter.py::test_pool_count_unchanged` **硬编码断言 `total == 2`**。

**含义**：如果你先跑了手工场景 B（提报了几单留在 `WAITING_HUMAN`），待办池里就不止 2 条 ⇒ 这个用例会**失败**。

**推荐顺序**：

```
1. pytest -q            ← 先跑自动化测试（此时 DB 是"干净"的基线状态）
2. 再跑手工场景 A/B/D  ← 手工测试会往 DB 里塞数据
3. 收尾：用归档脚本把遗留挂起单归档
```

**收尾归档**（[`backend/scripts/archive_stale_pending.py`](backend/scripts/archive_stale_pending.py)）：

```bash
# ① 预览（默认就是 dry-run，不改数据）
python scripts/archive_stale_pending.py --list

# ② 按时间归档早于某时刻的挂起单
python scripts/archive_stale_pending.py --before 2026-01-01 --apply

# ③ 归档指定 thread_id
python scripts/archive_stale_pending.py --thread-id manual_test_s1_xxxx --apply
```

> 📌 该脚本默认 **dry-run**，必须显式加 `--apply` 才真正写库 —— 这是防误操作的设计。

---

### 4.3.4 场景 D · SSE 流式对话

#### D.1 发起一次流式对话

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/agent/chat-stream \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"thread_id":"manual_sse_001","session_id":"manual_test_s1","message":"装设接地线前必须先做什么？"}'
```

> `-N` = 不缓冲（Git Bash / curl）。PowerShell 用 `curl.exe -N ...` 同理。

**期望（伪向量模式下）**：

```
event: token
data: {"type":"token","content":"知识库中暂未检索到与该问题直接相关的规程依据，请核实问题或联系管理员确认。"}

event: done
data: {"type":"done"}
```

**期望（真语义模式下）**：

```
event: token
data: {"type":"token","content":"装设接地线前"}
event: token
data: {"type":"token","content":"必须先验电确认无电压。"}
... （多帧）
event: ui_card
data: {"type":"ui_card","card_type":"power_grid_citations","data":{"citations":[{...}]}}
event: done
data: {"type":"done"}
```

#### D.2 三条路径的判别

| 路径 | 帧序列 | 触发条件 |
|---|---|---|
| **正常** | `token`* → `ui_card`（`card_type=power_grid_citations`）→ `done` | 召回非空 **且** LLM 可用 |
| **无召回** | `token`（**仅 1 帧**）→ `done` | 召回为空 —— `chat.py` 的 `if not rows: return` 提前返回，**不发 `ui_card`** |
| **异常** | `token`* → `error`（**没有 `done`**） | LLM 抛异常且已产出部分内容 |

**空消息路径**：

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/agent/chat-stream \
  -H "Authorization: Bearer $TOKEN_APPLICANT" \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"manual_sse_empty","session_id":"manual_test_s1","message":"   "}'
```

**期望**：

```
event: error
data: {"type":"error","message":"消息内容为空，请输入需要咨询的安规问题。"}
```

#### D.3 落库验证

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT thread_id, assigned_role, status, idempotency_key
   FROM ai_thread_mappings WHERE thread_id LIKE 'chat_manual_sse%';"

docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT role, kind, length(content) AS len FROM ai_chat_messages
   WHERE thread_id LIKE 'chat_manual_sse%' ORDER BY created_at;"
```

**期望**：

| 表 | 期望 |
|---|---|
| `ai_thread_mappings` | `thread_id = 'chat_manual_sse_001'`（**注意前缀 `chat_`**）、`assigned_role='SYSTEM'`、`status='ACTIVE'`、`idempotency_key='chat:chat_manual_sse_001'` |
| `ai_chat_messages` | **2 行**：第 1 行 `role='user'`（用户原文）、第 2 行 `role='assistant'`（完整回答，**不含**流式分片） |

> 📌 **`chat_` 前缀的作用**：聊天线程与业务工单线程在**同一个 `thread_id` 命名空间**里共存，`build_chat_thread_id()` 幂等地加上前缀，避免前端随手传一个 `session_id` 就把业务工单的检查点覆盖掉。

#### D.4 执行留痕（`ai_execution_traces`）

```bash
docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT node_name, model_name, prompt_tokens, completion_tokens, latency_ms, error_log
   FROM ai_execution_traces WHERE thread_id='chat_manual_sse_001';"
```

**留痕边界（精确口径 —— 这张表比很多人以为的要稀疏得多）**：

| 分支 | 是否写 trace | 原因 |
|---|---|---|
| 召回为空（`if not rows: return`） | ❌ **不写** | 提前 `return`，到不了第 3 步 |
| `llm is None`（未配 `OPENAI_API_KEY`） | ❌ **不写** | `if llm is None: ... return`，同样提前返回 |
| LLM 正常流式生成 | ✅ **写 1 行** | `node_name='chat.stream'`，`model_name=resolve_model_name()` |
| LLM 抛异常（超时 / 限流） | ✅ **写 1 行** | `except` 捕获后仍流到第 3 步，`error_log` 写 `{类型}: {消息}` |
| **状态机四节点**（`safety_check` / `oms_draft` / `human_audit` / `issue_permit`） | ❌ **一条都不写** | 这四个节点没有任何 `trace_sink` 调用 |

> 🔑 **所以在当前配置下（召回为空），`ai_execution_traces` 表格会是空的** —— 这是**预期行为**，不是 bug。跑完场景 B（工单全流程）后再查这张表，依然是空的，因为状态机节点不留痕。

#### D.5 前端流式体验验证

1. 打开 `http://localhost:5173`，切到「张三」。
2. 中栏输入「装设接地线前必须先做什么？」并发送。
3. **期望**：文字**逐字/逐块**浮现（打字机效果），而非整段瞬间出现。
4. **期望**：回答结束后，状态灯从 `connected` 回到 **`Idle`（灰）**。
5. **期望**：切到别的会话再切回来，消息仍在（IndexedDB 恢复）。
6. **期望**：刷新浏览器后消息仍在。

---

## 4.4 已知踩坑与预期失败对照表

> **分类图例**：
> 🔧 **环境问题** = 你的机器没配好 ｜ 🎯 **设计如此** = 代码有意为之 ｜ ⚠️ **预期失败** = 当前配置的必然结果 ｜ ❌ **真 bug** = 需要修代码

| 现象 | 分类 | 根因 | 处置 |
|---|---|---|---|
| `docker compose up -d` 报 `required variable DB_PASSWORD is missing a value` | 🔧 | Compose 只读**项目根**的 `.env`，而 `.env` 在 `backend/` 下 | `docker compose --env-file backend/.env up -d` |
| 宿主机 `psql: command not found` | 🔧 | 机器上没装 psql | 一律用 `docker exec -i power_ai_postgres psql -U "$DB_USER" -d "$DB_NAME"` |
| Git Bash 里 `conda: command not found` | 🔧 | conda 不在 Git Bash PATH | `export PATH="/c/Users/lj/miniconda3/envs/power-agent:$PATH"` 或直接用绝对路径 |
| PowerShell 里 `curl` 行为怪异（不发送 POST body） | 🔧 | `curl` 是 `Invoke-WebRequest` 别名 | 写 **`curl.exe`** |
| 控制台中文乱码 | 🔧 | Windows 默认 GBK | `chcp 65001` + `$env:PYTHONIOENCODING="utf-8"` |
| `pytest` 报 `no tests ran` / 找不到测试 | 🔧 | `backend/tests/*` 被 `.gitignore`，新克隆机器上目录为空 | 本机已有该目录；若确为空需从有记录的机器拷贝 |
| `uvicorn` 启动后跑 pytest，后端反复重启 | 🔧 | `--reload` 的 watchdog 监视 cwd，pytest 写 `.pyc` 触发重载 | 手工测试时用 `uvicorn main:app --port 8000`（不带 `--reload`） |
| `compose` 打印 `the attribute 'version' is obsolete` | 🔧 | Compose v2 废弃 `version:` 字段 | 忽略，无害 |
| **`/knowledge/search` 默认阈值返回 `[]`** | ⚠️ | 伪向量与存量真向量正交，余弦低于 0.5 | 走 A.6 修复；或临时把 `min_similarity` 降到 0 |
| **`/knowledge/search` 阈值 0 时相似度只有 0.07~0.08 且命中错文档** | ⚠️ | 同上，这是伪向量的指纹 | 同上 |
| `/knowledge/ask` 返回「知识库中暂未检索到…」 | ⚠️ | 召回为空 | 同上；或按 A.6 修好后复测 |
| `tests/test_rag2.py` 显示 `skipped` | 🎯 | 向量降级时该用例**主动 skip** | 设计如此；修好向量后应变成 passed |
| **`chat-stream` 只有 token + done，没有 `ui_card`** | ⚠️ | 召回为空 ⇒ `chat.py` 提前 return | 修好向量服务后复现 |
| `ai_execution_traces` 表几乎为空 | 🎯 | 只有 chat 路径且召回非空时才写；状态机节点零留痕 | 设计如此（可观测性缺口见第五章） |
| `pytest tests/stress_cas_concurrency.py` 失败 / IndexError | ❌ | 脚本发的字段名是 `is_permitted`，线上契约是 `approved` ⇒ 全部 422 | 脚本过期，见第六章 P1；**线上接口本身正常** |
| `pytest tests/verify_cas_manual.py` 收集期报错 | ❌ | `from app.core.database import checkpointer_pool` —— 该名字不存在，实际是 `checkpointer_manager` | 同上 |
| `test_pending_pool_filter.py::test_pool_count_unchanged` 失败 | ❌ | 硬编码断言 `total == 2`，手工提报后待办池数量变了 | 先跑 pytest 再跑手工场景；或用归档脚本收尾 |
| `GET /health` 返回 `graph_ready: false` | 🔧 | 插件没声明 `graph_factory` 或 `graph_name` 不匹配 | 对齐 `POWER_GRAPH_NAME` |
| `GET /plugin/manifest` 无需 Token 就能访问 | 🎯 | 该端点**故意不加鉴权**（前端启动时就要拿它） | 设计如此；生产加固见第六章 P2 |
| `GET /tasks` 用提报员令牌返回 200 + 空列表（不是 403） | 🎯 | 代码注释明示「允许访问，安全返回空列表，不抛 403」 | 设计如此 |
| `POST /audit` 用提报员令牌返回 403 | 🎯 | `require_roles(['DISPATCHER'])` 门禁 | 设计如此 |
| `POST /audit` 返回 422 | ❌ | 请求体字段名写成了 `is_permitted` | 应为 **`approved`**（见 `AuditRequest`） |
| `POST /audit` 返回 409「任务已被其他操作人处理或版本已失效」 | 🎯 | CAS 抢占失败（重复提交 / 并发抢单 / 版本已变） | 重新拉取待办池拿最新 `lock_version` |
| `ai_thread_mappings.biz_order_id` 恒为 NULL | ❌ | `create_mapping` 无该形参，Router 也没补 UPDATE | 见第六章 P0；真实单号在 `card_payload` 与图状态里 |
| `ai_thread_mappings.current_node` 恒为 NULL | ❌ | 状态机指针从不回写 | 见第六章 P1 |
| `SAFETY_REJECTED` 的 `lock_version` 停在 1 | 🎯 | 这条路径**没有 CAS**（没人核签），归档即终态 | 设计如此 |
| `PERMITTED` / `REJECTED` 的记录**没有**被归档 | 🎯 | 只有安规否决路径才 `archive()` | 设计如此（终态单据保留审计链路） |
| `GET /tasks` 的 `total` 比预期多/少 | ❌ | 库里残留了历史挂起单 | `python scripts/archive_stale_pending.py --list` 查看，再 `--apply` 归档 |
| `python -m tests.test_core_graph` 的输出与线上行为对不上 | 🎯 | 历史脚本，线上早已重构 | **不得当验收依据** |
| `CLAUDE.md` 里写的 `app/agent/graph.py`、`PlanState`、SQLite 找不到 | 🎯 | 文档描述的是重构前的架构 | 以本文档为准；详见第五章「文档漂移专节」 |
| 右栏「运行追踪」面板恒显示「暂无数据」 | 🎯 | 前端占位，尚未接 `ai_execution_traces` | 见第六章 P2 |
| SSE 状态灯 `Idle`（灰） | 🎯 | `idle` = **当前没有进行中的对话流**，不代表后端不可达 | 想验证连通性请打 `/api/v1/health` |
| 临时语料 `_smoke_test.md` 出现在 `git status` 里 | 🔧 | `plugins/power_grid/documents/` **被 git 跟踪**（不同于 `tests/`） | A.7 删除该文件 |
| `alembic downgrade` 后 `ai_*` 表消失 | 🔧 | downgrade 会删表 | 本手册任何步骤都不需要 downgrade |

---

## 4.5 端点契约速查表

> 写自动化测试脚本时直接查这张表。

| 方法与路径 | 鉴权 | 请求体 | 成功响应 | 失败响应 |
|---|---|---|---|---|
| `GET /api/v1/health` | 无 | — | `{code:200, status:"ok", plugin, graph_ready}` | — |
| `POST /api/v1/auth/login` | 无 | `{user_id}` | `{access_token, token_type:"bearer", user}` | 401 `账号 {id} 不存在或无权登录。` |
| `GET /api/v1/auth/me` | Bearer | — | 当前用户载荷 | 401 |
| `GET /api/v1/plugin/manifest` | **无** | — | `{name, version, endpoints, identities}` | — |
| `POST /api/v1/knowledge/search` | Bearer | `{query, biz_tag?, doc_code?, top_k=3, min_similarity=0.5}` | **裸数组** `[{doc_code, biz_tag, section_title, content, similarity}]` | 401 |
| `POST /api/v1/knowledge/ask` | Bearer | `{query, biz_tag?, doc_code?}` | `{question, answer, citations[]}` | 401 |
| `POST /api/v1/power-dispatch/apply` | Bearer | `{session_id, substation, voltage_level, operation_task, safety_measures[]}` | 挂起：`{thread_id, status:"WAITING_HUMAN", interrupted:true, card}`<br>否决：`{thread_id, status:"SAFETY_REJECTED", interrupted:false, message, card:{}}` | 401 |
| `GET /api/v1/power-dispatch/tasks` | Bearer | — | `{total, reviewer_id, items[]}` | 401 |
| `GET /api/v1/power-dispatch/messages?thread_id=` | Bearer | — | `{thread_id, requester_id, items[]}` | 401 |
| `POST /api/v1/power-dispatch/audit` | Bearer + `DISPATCHER` | `{thread_id, lock_version, approved, opinion}` | `{thread_id, status:"PERMITTED"\|"REJECTED", permit_info}` | 401 / 403 / 409 |
| `POST /api/v1/agent/chat-stream` | Bearer | `{thread_id, session_id, message, action_payload?}` | SSE 流：`token` / `ui_card` / `error` / `done` | 401 |

### 状态机状态取值速查

| 状态 | 出现位置 | 含义 |
|---|---|---|
| `DRAFT` | `ThreadMappingStore` 默认 | 通用初态 |
| `ACTIVE` | 聊天线程 | 无状态机的纯对话线程 |
| `WAITING_HUMAN` | 工单提报 | 挂起，等待人工核签 |
| `RUNNING` | CAS 抢占后的瞬时态 | 已被某个操作人抢占 |
| `PERMITTED` | 终态 | 核签通过，许可令已签发 |
| `REJECTED` | 终态 | 核签驳回 |
| `SAFETY_REJECTED` | 终态 | 安规校验未通过，提报阶段即否决（**已归档**） |

### 卡片类型速查

| `card_type` | 何时下发 | 关键字段 |
|---|---|---|
| `dispatcher_audit` | 提报通过安规校验、进入待核签 | `thread_id`, `biz_order_id`, `substation`, `voltage_level`, `operation_task`, `violations[]`, `lock_version` |
| `permit_result` | 核签完成（通过或驳回都发） | `thread_id`, `status`, `biz_order_id`, `permit_info`, `opinion` |
| `power_grid_citations` | 对话召回非空时 | `data.citations[]`：`doc_code`, `section_title`, `content`, `similarity`（4 位小数） |

---

---

# 第五章 现有代码存在的问题、技术债与风险清单

> **本章只列问题，不含建议**（改进建议见第六章）。
>
> **每条格式**：`文件路径` → `等级` → `现象` → `影响` → `证据`。
> **等级定义**：
>
> | 等级 | 含义 | 处置要求 |
> |---|---|---|
> | 🔴 **高** | 已在生产逻辑上产生错误结果，或存在静默失效 | 立即修复（P0） |
> | 🟠 **中高** | 存在越权/数据一致性缺口，安全或审计上不可接受 | 近期修复（P0/P1） |
> | 🟡 **中** | 不影响当前演示，但会在真实接入/生产化时爆雷 | 排期修复（P1） |
> | ⚪ **低** | 技术债、死代码、可维护性 | 有余力时清理（P2） |

## 5.0 风险速查表

| 等级 | 条数 | 编号 |
|---|---|---|
| 🔴 高 | **3** | H1 / H2 / H3 |
| 🟠 中高 | **2** | M1 / M2 |
| 🟡 中 | **12** | M3 ~ M14 |
| ⚪ 低 | **7** | L1 ~ L7 |
| **合计** | **24** | |

| 编号 | 一句话摘要 | 主要落点 |
|---|---|---|
| **H1** | 向量服务供应商错配 → **静默降级为 MD5 伪向量**，RAG 语义能力整体失效且 HTTP 层不可见 | `backend/app/core/rag/embeddings.py` |
| **H2** | **完全没有电压等级风险定级** —— 110kV/220kV/500kV 与 10kV 走完全相同的判定路径 | `backend/app/plugins/power_grid/graph.py` |
| **H3** | `safety_check_node` 把 RAG 召回结果**整个丢弃**，安规判定实为两条关键词子串匹配 | `backend/app/plugins/power_grid/graph.py` |
| **M1** | `ai_thread_mappings.biz_order_id` 列**恒为 NULL** | `core/workflow/thread_mapping_store.py` + `plugins/power_grid/router.py` |
| **M2** | `GET /messages` **无归属鉴权**，任意登录用户可读任意工单的消息与卡片 | `backend/app/plugins/power_grid/router.py` |
| **M3** | `OMSGatewayAdapter.update_order_status` **生产代码从未调用**，OMS 单号状态永不回写 | `plugins/power_grid/adapters/oms_adapter.py` |
| **M4** | `ai_execution_traces` 覆盖面极窄：状态机四个节点**零留痕** | `backend/app/api/v1/agent.py` + `plugins/power_grid/chat.py` |
| **M5** | `async_engine` 硬编码 `echo=True`，生产打印全量 SQL | `backend/app/core/database.py` |
| **M6** | `get_db_session()` 定义即废，14 处调用点各自裸开连接 | `backend/app/core/database.py` |
| **M7** | `action_payload` 前端契约在后端**无消费方**，交互动作被静默丢弃 | `backend/app/schemas/a2ui.py` |
| **M8** | `ai_thread_mappings.current_node` **恒为 NULL**，状态机指针不可回查 | `backend/app/models/ai_schema.py` |
| **M9** | 两个压力脚本必然失败（`is_permitted`→422 / 不存在的导入名） | `backend/tests/` |
| **M10** | `test_pending_pool_filter.py` 硬编码 `total == 2`，顺序依赖型活雷 | `backend/tests/test_pending_pool_filter.py` |
| **M11** | `qa_llm` 是**模块级**构造，测试无法注入 → 用例会真的联网 | `backend/app/api/v1/knowledge.py` |
| **M12** | `backend/tests/*` 整个目录被 gitignore，**12 个测试资产永不入库** | `.gitignore` |
| **M13** | 蓝图文档 / `CLAUDE.md` / `project-docs` 与实现**全面漂移** | 仓库根 + `project-docs/` |
| **M14** | 无 `vue-router` / 无 `pinia` / 无前端测试基座 | `frontend/package.json` |
| **L1** | CORS `allow_origins=["*"]` + `allow_credentials=True` 组合过宽 | `backend/main.py` |
| **L2** | 知识库软删除**无恢复路径** | `backend/app/core/rag/vector_service.py` |
| **L3** | `content_hash` 不含 `biz_tag`，跨标签去重可能串味 | `backend/app/core/rag/chunking.py` |
| **L4** | `plugins/power_grid/schemas.py` 整文件死代码 | `backend/app/plugins/power_grid/schemas.py` |
| **L5** | 前后端共 4 处死导出 | 前端 3 处 + 后端 1 处 |
| **L6** | 前端「运行追踪」面板恒为占位，未接 `ai_execution_traces` | `frontend/src/core/views/` |
| **L7** | `ai_*` 四表**零 ForeignKey**，引用完整性全靠应用层自觉 | `backend/app/models/ai_schema.py` |

---

## 5.1 🔴 高风险（3 条）

### 🔴 H1 · 向量服务供应商错配 → 静默降级为 MD5 伪向量

| 项 | 内容 |
|---|---|
| **落点** | `backend/app/core/rag/embeddings.py`（`EmbeddingService.__init__` / `get_embeddings`） |
| **现象** | `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` 未配置时，代码回退复用聊天侧 `OPENAI_API_KEY` / `OPENAI_BASE_URL`（`ENV_FALLBACK_API_KEY` / `ENV_FALLBACK_BASE_URL`），而 `EMBEDDING_MODEL_NAME` 仍指向另一家供应商的向量模型。请求发出后供应商返回**空 data**，openai SDK 抛**裸 `ValueError`**，被 `except` 捕获后**静默返回 MD5 伪向量**。 |
| **影响** | ① **RAG 语义检索彻底失效**，且用户看到的响应毫无异常；② `ai_knowledge_base` 里存的是早期真实语义向量，查询端发的是伪向量，**两种表示空间混在同一张表**；③ 伪向量是内容的确定性哈希，检索结果退化为"字面哈希近似"，命中文档与问题语义无关。 |
| **证据** | 【实测】`backend/.env` 实际缺少 `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` 两个键；【实测】`/knowledge/search` 在默认 `min_similarity=0.5` 下返回 `[]`，降到 `0` 时相似度仅 **0.072~0.082** 且命中错误文档；【实测】用库中原文当 query 复算相似度 ≈ **1.000000**（伪向量自洽），而对存量真向量行 ≈ **-0.06**（近乎垂直）；【源码】`get_embeddings` 的异常分支只打 `logger.warning` / `logger.exception`，**不置任何标志位、不落库**，`search_advanced` 也不校验返回值来源 ⇒ HTTP 响应层**完全不可见**。 |

> 📌 **同类隐患（同一文件）**：`EMBEDDING_BATCH_SIZE = 8` 的锁定注释说明「当前编码套餐 embeddings 入口在单批 ≥16 时会落入与 ≤8 不同的表示空间，二者余弦≈0 完全正交」。这是**真实存在过的生产事故**，且**与 H1 的表现完全一样**（检索全失效）。两个问题叠加后，RAG 链路同时踩着"供应商错配"和"批量空间错乱"两颗雷，且**都无法从响应中分辨**。

### 🔴 H2 · 完全没有电压等级风险定级

| 项 | 内容 |
|---|---|
| **落点** | `backend/app/plugins/power_grid/graph.py::safety_check_node` |
| **现象** | 安规判定只做两件事：把 `safety_measures` 拼成字符串，然后检查是否包含 `"接地线"` 与 `"验电"` 两个**子串**。**没有任何一处代码读取 `voltage_level`**。 |
| **影响** | 110kV / 220kV / 500kV 重大检修与 10kV 低压检修走**完全相同**的判定路径：同样的安措，10kV 会因缺关键词被否决，500kV 也一样。项目 `CLAUDE.md` 明文承诺的「高压/超高压必须定级 `HIGH` 并强制挂起人工核签、低压自动签发」在代码中**不存在**。 |
| **证据** | 【源码】`graph.py` 全文无 `voltage_level` 分支；【源码】`state.get("voltage_level")` 只被拼进 RAG 查询串 `f"{voltage_level} {operation_task}"`，而该查询结果**根本没被使用**（见 H3）；【对照】项目 `CLAUDE.md`「二、电力业务红线与状态机判定规约」章节描述的定级规则与实现不符。 |

> 🚨 **这是本项目最严重的合规缺口**：电力检修的红线是"高压必核签、低压可自决"，而代码里高压与低压**一样对待**。所幸 `safety_check_node` 之后的 `human_audit` 节点**无条件**挂起人工核签（并非按风险定级选择挂起），所以当前**不会**出现"高压无人核签"的越权放行 —— 但一旦有人按 `CLAUDE.md` 的描述去改造，把挂起改成条件触发，就会直接开出一个高危漏洞。**当前是"侥幸安全"，不是"设计安全"。**

### 🔴 H3 · `safety_check_node` 把 RAG 召回结果整个丢弃

| 项 | 内容 |
|---|---|
| **落点** | `backend/app/plugins/power_grid/graph.py::safety_check_node` |
| **现象** | 节点内调用了 `await VectorStoreService().search_advanced(query=f"{voltage_level} {operation_task}", biz_tag=RAG_BIZ_TAG, top_k=RAG_TOP_K, min_similarity=RAG_MIN_SIMILARITY)`，但**返回值没有赋给任何变量**；`try/except` 的 `except Exception: pass` 又把任何异常一并吞掉。随后节点只返回基于两条关键词的 `violations`。 |
| **影响** | 安规判定**与《电网安全工作规程》的真实条款完全脱钩**。规程检索只在"看起来像是做了检索"的表象下运行，实际结果对业务零影响。叠加 H1 后，这行代码还会**每次提报都发起一次注定无效的向量请求**（浪费一次外网往返 + 一次批量嵌入调用）。 |
| **证据** | 【源码】`graph.py` 中该调用为独立表达式语句，无赋值；`except Exception: pass`；【实测】配合 H1 的伪向量状态，`/knowledge/search` 类查询在此处亦返回空。 |

> 📌 **这三个高危项互相放大**：H1 让召回必空 → H3 让召回结果被丢弃 → H2 让整个判定退化为两条字符串匹配。**当前的安规校验实质上是"关键词正则"，不是"规程检索"。**

---

## 5.2 🟠 中高风险（2 条）

### 🟠 M1 · `ai_thread_mappings.biz_order_id` 列恒为 NULL

| 项 | 内容 |
|---|---|
| **落点** | `backend/app/core/workflow/thread_mapping_store.py::ThreadMappingStore.create_mapping`（无 `biz_order_id` 形参）<br>`backend/app/plugins/power_grid/router.py::apply_dispatch`（拿到 OMS 单号后未补 UPDATE）<br>`backend/app/models/ai_schema.py`（列与索引均已建） |
| **现象** | 表里**有** `biz_order_id` 列**和**索引，但 `create_mapping` 的签名里根本没有这个参数，Router 拿到 `biz_order_id` 之后也没有回写语句 ⇒ **该列永远为 NULL**。真实的 OMS 单号只存在于两处：LangGraph 图状态 `state["biz_order_id"]` 与 `ai_chat_messages.card_payload->>'biz_order_id'`。 |
| **影响** | ① **审计链路断裂** —— 无法用一条 SQL 把「本地工单 ↔ 真实 OMS 单」对起来；② 表上那个索引是**纯装饰**（永远匹配不到）；③ 与真实 OMS 集成时，弱引用设计会退化成"单号只存在于 JSON 里"，无法做外键级联或一致性校验。 |
| **证据** | 【源码】`create_mapping(thread_id, session_id, creator_id, creator_role, assigned_role, creator_dept, status, idempotency_key)` —— 无 `biz_order_id`；【实测】DB 中 19 行 `ai_thread_mappings` 的 `biz_order_id` 全部为 NULL。 |

### 🟠 M2 · `GET /messages` 无归属鉴权

| 项 | 内容 |
|---|---|
| **落点** | `backend/app/plugins/power_grid/router.py::list_thread_messages` |
| **现象** | 端点只校验"已登录"（`Depends(get_current_user)`），**不校验当前用户与该 `thread_id` 是否有关**。任何持有效 Token 的用户只要拿到（或猜到）`thread_id`，就能读到该工单的完整消息流 —— 含 `dispatcher_audit` 卡片（变电站名、电压等级、作业内容、违规隐患）、`permit_result` 卡片（调度令编号、CA 签名哈希）、以及 `audit_opinion`（审批意见）。 |
| **影响** | **横向越权读取**。在多租户/多部门场景下，提报员能看到别人的工单详情与审批意见；`thread_id` 形如 `{session_id}_{12位hex}`，虽不易枚举，但 `session_id` 常由前端本地生成、可能出现在日志或 URL 中，可被利用。 |
| **证据** | 【源码】`list_thread_messages` 中无 `creator_id` / `assigned_role` 与 `current_user["sub"]` 的比对逻辑；对照 `list_tasks` 对非 `DISPATCHER` 角色返回空列表的做法，此处**没有**同等保护。 |

> 📌 **同一插件的 `POST /audit` 做了角色门禁（`require_roles([POWER_ROLE_DISPATCHER])`），`GET /tasks` 做了角色过滤，唯独 `GET /messages` 漏了归属校验** —— 明显是遗漏而非有意设计。

---

## 5.3 🟡 中风险（12 条）

### 🟡 M3 · `OMSGatewayAdapter.update_order_status` 生产代码从未调用

- **落点**：`backend/app/plugins/power_grid/adapters/oms_adapter.py`（方法已实现）、`backend/app/services/acl/protocols.py::OrderAdapterProtocol`（协议已声明）
- **现象**：`update_order_status(order_id, status, opinion)` 方法与 Protocol 声明都齐备，但**全仓库只有 `backend/tests/test_acl.py` 调用它**。工单终态（`PERMITTED` / `REJECTED` / `SAFETY_REJECTED`）**从不回写 OMS**。
- **影响**：接入真实 OMS 后，本地库显示"已核准"而 OMS 侧仍是"待审批"，**双向状态必然对不上**；防腐层（Anti-Corruption Layer）的"翻译"契约形同虚设。
- **证据**：【实测】全仓库 `update_order_status` 命中点仅 4 处：协议声明、适配器实现、适配器 docstring、测试调用。

### 🟡 M4 · `ai_execution_traces` 覆盖面极窄，状态机四节点零留痕

- **落点**：`backend/app/api/v1/agent.py::TraceWriter`（唯一写入方）、`backend/app/plugins/power_grid/chat.py`（唯一调用方）
- **现象**：`ai_execution_traces` 表设计了 `node_name` / `model_name` / `prompt_tokens` / `completion_tokens` / `total_cost` / `latency_ms` / `tool_calls` / `error_log` 等一整套可观测字段，但：
  1. 状态机的四个节点（`safety_check` / `oms_draft` / `human_audit` / `issue_permit`）**没有任何 `trace_sink` 调用**；
  2. 对话路径里，**召回为空**时提前 `return`，**不写 trace**；
  3. `build_chat_model()` 返回 `None` 时提前 `return`，**也不写 trace**。
  4. 反过来，**LLM 抛异常时反而会写**（`except` 捕获后仍流到写入点，`error_log` 记 `{类型}: {消息}`）。
- **影响**：**最需要留痕的场景（工单全流程）一条 trace 都没有**；而**最不需要留痕的场景（连规程都没召回到）也不写** ⇒ 表几乎是空的。排障时无法回答"这单卡在哪一步、耗时多久、调了什么模型"。
- **证据**：【实测】当前 `ai_execution_traces` 表行数为 0（伪向量模式下召回恒空）；【源码】`chat.py` 中 `if not rows: ... return` 与 `if llm is None: ... return` 两处提前返回均位于 trace 写入点之前。

### 🟡 M5 · `async_engine` 硬编码 `echo=True`

- **落点**：`backend/app/core/database.py`（`create_async_engine(..., echo=True)`）
- **现象**：`echo=True` 写死在引擎构造里，**没有环境变量开关**。
- **影响**：生产环境会把**全量 SQL 与参数**打进 stdout/stderr（含 `ai_chat_messages.content` 原文、`ai_thread_mappings.audit_opinion`、人员工号等业务明文）。既是**信息泄露面**，也是**性能与日志体积问题**。
- **证据**：【源码】`core/database.py` 中 `echo=True` 为字面量。

### 🟡 M6 · `get_db_session()` 定义即废，14 处调用点各自裸开连接

- **落点**：`backend/app/core/database.py::get_db_session`（提供 FastAPI 依赖注入函数）<br>调用点：`core/workflow/hitl.py`、`core/workflow/thread_mapping_store.py`、`core/workflow/message_recorder.py`、`core/rag/vector_service.py`、`plugins/power_grid/router.py` 等
- **现象**：底座精心提供了 `get_db_session()` 这个标准依赖注入入口，但**没有任何路由使用 `Depends(get_db_session)`**；各处一律 `async with AsyncSessionLocal() as session:` 自己开、自己提交。
- **影响**：① **事务边界分散** —— 一次业务操作被切成多段独立事务（例如 `resume_with_cas` 的 CAS UPDATE 先提交，图恢复再执行，中途失败会留下"已抢占但未完成"的 RUNNING 状态）；② 连接生命周期脱离框架管控，无法统一设置只读副本、超时、隔离级别；③ 与项目规范「全链路纯异步 + 统一会话管理」相悖。
- **证据**：【实测】全仓库 `AsyncSessionLocal()` 直接调用点约 14 处，`get_db_session` 除定义外**零引用**。

### 🟡 M7 · `action_payload` 前端契约在后端无消费方

- **落点**：`backend/app/schemas/a2ui.py::AgentChatRequest.action_payload`（已定义，`Optional[dict[str, Any]]`）<br>`backend/app/api/v1/agent.py`（**未读取该字段**）
- **现象**：请求模型预留了"交互动作载荷"，但端点实现从头到尾没碰过它。`backend/app/plugins/power_grid/schemas.py` 里甚至有一段"前端 `action_payload` 中审核决定的别名归一映射"的常量表（该文件本身已是死代码，见 L4），**却没有任何代码路径使用**。
- **影响**：A2UI 协议设计里的"卡片 → 用户动作 → 回传后端"这条回路**没有接通**。前端发送的任何交互动作被**静默丢弃**，用户看不到任何报错。
- **证据**：【实测】全仓库 `action_payload` 命中点：`schemas/a2ui.py` 定义 1 处、`plugins/power_grid/schemas.py` 注释 1 处，**`api/v1/agent.py` 零命中**。

### 🟡 M8 · `ai_thread_mappings.current_node` 恒为 NULL

- **落点**：`backend/app/models/ai_schema.py`（列存在、nullable、有索引）<br>`backend/app/core/workflow/thread_mapping_store.py`（`create_mapping` 不写、`get` 会读）
- **现象**：状态机执行指针从不回写。`ThreadMappingStore.get()` 明明把 `current_node` 读进了返回字典，但它的值永远是 `None`。
- **影响**：无法从 DB 反查"这条工单走到哪个节点了"，也无法实现"断点恢复时定位当前节点"。前端左栏的会话项里 `current_node: null`（`useWorkbenchStore.ts::applyResult`）也是硬编码的 `null`。
- **证据**：【实测】DB 中 19 行 `current_node` 全部为 NULL。

### 🟡 M9 · 两个压力脚本必然失败

- **落点**：`backend/tests/stress_cas_concurrency.py`、`backend/tests/verify_cas_manual.py`
- **现象**：
  1. `stress_cas_concurrency.py` 构造的请求体发的是 `{"is_permitted": True}`，而线上 `AuditRequest` 的字段名是 **`approved`** ⇒ 全部请求返回 **422** ⇒ 脚本取 `success[0]` ⇒ **IndexError** 收尾（不是断言失败，是脚本崩溃）。
  2. `verify_cas_manual.py` 里 `from app.core.database import checkpointer_pool` —— **这个导出名不存在**，实际导出的是 `checkpointer_manager`（`CheckpointerManager` 实例）⇒ 收集期就报 ImportError。
- **影响**：这两个脚本是**并发安全验证的唯一资产**，却一个跑不通、一个根本 import 不了。CAS 乐观锁的正确性目前**只有单线程重放（B.5）这一条验证路径**在守护。
- **证据**：【源码】`AuditRequest{thread_id, lock_version, approved, opinion}`（`plugins/power_grid/router.py`）；【实测】`core/database.py` 的导出是 `checkpointer_manager`，无 `checkpointer_pool`。
- ⚠️ **注意**：这两个文件**不会被裸跑 `pytest` 收集**（`pytest.ini` 未覆盖 `python_files`，默认只收 `test_*.py` / `*_test.py`），详见第四章 C.3。

### 🟡 M10 · `test_pending_pool_filter.py` 硬编码 `total == 2`

- **落点**：`backend/tests/test_pending_pool_filter.py::test_pool_count_unchanged`
- **现象**：断言"归档一条前后待办池数量不变"时，写死了 `total == 2`。
- **影响**：**顺序依赖型活雷** —— 只要手工测试提报过任何一单留在 `WAITING_HUMAN`，这个用例就必然失败。而"手工测试与自动化测试共用同一个开发库"恰恰是本项目的现实状态。
- **证据**：【源码】用例内为字面量比较；【实测】DB 当前 `ai_thread_mappings` 已有 19 行历史挂起记录。

### 🟡 M11 · `qa_llm` 是模块级构造，测试无法注入

- **落点**：`backend/app/api/v1/knowledge.py`（模块导入期即 `qa_llm = build_chat_model(temperature=0.1)`）
- **现象**：LLM 客户端在 **import 期**构造完成。测试若想"关掉 LLM 走降级分支"，只能 monkeypatch 环境变量 `OPENAI_API_KEY` —— 但**此时模块早已导入完毕**，`qa_llm` 早已固化为真实客户端。
- **影响**：① 测试**无法**确定性覆盖降级分支；② 一旦把向量服务修好（见 H1 修复路径），`test_rag_api.py` 会**真的联网**打 LLM —— 网络抖动 / 限流 / 计费都会让测试变成"薛定谔的 flaky"。
- **证据**：【源码】`qa_llm` 位于模块顶层（import 期执行），`build_chat_model()` 内部在无 Key 时才返回 `None`。

### 🟡 M12 · `backend/tests/*` 整个目录被 gitignore

- **落点**：`.gitignore`（规则 `backend/tests/*` + 例外 `!backend/tests/.gitkeep`）
- **现象**：12 个测试文件（含 `test_acl.py` / `test_ai_schema.py` / `test_dispatch_workflow.py` / `test_pending_pool_filter.py` / `test_rag_api.py` / `test_rag2.py` / `stress_*.py` 等）**全部不入库**。
- **影响**：① **新克隆的机器上 `backend/tests/` 是空的**，`pytest` 直接 `no tests ran`；② CI 无从建立；③ 团队协作时测试资产只能靠"私下拷贝"传递；④ 本文档第四章的场景 C **在别人机器上无法执行**。
- **证据**：【实测】`git status --porcelain` 中 `backend/tests/` 全部条目为 untracked/ignored。

### 🟡 M13 · 蓝图文档 / `CLAUDE.md` / `project-docs` 与实现全面漂移

- **落点**：仓库根 `企业级通用 AI Agent 通用脚手架 · 落地开发与架构全景指南.md`（122 KB）、项目根 `CLAUDE.md`、`project-docs/overall-structure.md`
- **现象**：三份文档描述的是**插件化重构之前**的架构。详见本章 **5.5 文档漂移专节**。
- **影响**：新成员按 `CLAUDE.md` 去找 `app/agent/graph.py`、`PlanState`、`dispatcher_approval`、`backend/app/schemas/dispatch.py`、SQLite `power_dispatch.db` —— **一个都找不到**；`CLAUDE.md` 里承诺的电压定级规则也不存在（H2）。这会**系统性地误导后续所有开发与 AI 助手**（包括本项目自身依赖的 `CLAUDE.md` 上下文）。
- **证据**：见 5.5 逐项对照表。

### 🟡 M14 · 无 `vue-router` / 无 `pinia` / 无前端测试基座

- **落点**：`frontend/package.json`（scripts 仅 `dev` / `build` / `preview`；依赖中无 `vue-router` / `pinia` / `vitest`）
- **现象**：页面切换靠组件内部 `ref` 状态；全局状态是 `frontend/src/core/workbench/useWorkbenchStore.ts` 里一个**模块级 `reactive()` 单例**（不是 Pinia store）；没有任何单元测试 / 组件测试框架。
- **影响**：① 状态管理无 devtools 时间旅行、无插件化、无类型推导增强；② 页面跳转不可深链接、不能后退；③ **前端没有任何自动化测试** —— 唯一门禁是 `npm run build`（`vue-tsc -b && vite build`），只验类型不验行为。
- **证据**：【实测】`package.json` 无上述依赖；【源码】`useWorkbenchStore.ts` 顶部为 `const state = reactive<WorkbenchState>({...})` + 导出的普通函数集合。

---

## 5.4 ⚪ 低风险 / 技术债（7 条）

### ⚪ L1 · CORS `allow_origins=["*"]` + `allow_credentials=True` 组合过宽

- **落点**：`backend/main.py`（`app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])`）
- **现象**：同时放开任意来源、任意方法、任意头、任意头携带凭证。
- **影响**：当前鉴权是 **Bearer Token**（存在 `localStorage`，不是 Cookie），所以 `allow_credentials` 并无必要，且浏览器不会自动带凭证 ⇒ **暂不可直接利用**。但一旦将来引入 Cookie 会话，这个组合会让**任意站点**都能带着用户凭证跨域调接口。
- **证据**：【源码】`main.py:76-82`。

### ⚪ L2 · 知识库软删除无恢复路径

- **落点**：`backend/app/core/rag/vector_service.py::soft_delete_document`
- **现象**：只把 `is_active` 置为 `FALSE`，**没有任何 un-delete / restore 接口**；`rag_ingest_file.py --overwrite` 走的也是软废止。
- **影响**：误删一个 `doc_code` 后，只能手工改库恢复；也无法实现"文档回滚到上一个版本"。
- **证据**：【源码】`soft_delete_document` 实现中只有 `is_active=False`；全仓库无 restore/un-delete 方法。

### ⚪ L3 · `content_hash` 不含 `biz_tag`

- **落点**：`backend/app/core/rag/chunking.py`（`content_hash = md5(f"{doc_code}:{content.strip()}")`）
- **现象**：去重键只由 `doc_code` + 正文构成，**不含 `biz_tag`**；且上游 `ParsedDocument.metadata` 未向下传递到切片对象。
- **影响**：同一份文档若被挂到两个业务标签下，去重逻辑可能把后一次的切片误判为重复而跳过；跨标签场景下切片语义归属会串味。
- **证据**：【源码】哈希拼接串中无 `biz_tag`。

### ⚪ L4 · `plugins/power_grid/schemas.py` 整文件死代码

- **落点**：`backend/app/plugins/power_grid/schemas.py`
- **现象**：文件内定义了"审核决定别名归一映射"等常量，**全仓库无任何 import**。
- **影响**：误导 —— 读者会以为存在一套"审核动作归一化"机制（而实际映射是直接写在 `router.py` 里的 `{"is_permitted": req.approved, ...}`）。
- **证据**：【实测】全仓库无 `from app.plugins.power_grid.schemas import` 或 `power_grid.schemas`。

### ⚪ L5 · 前后端共 4 处死导出

| 符号 | 落点 | 状态 |
|---|---|---|
| `resumeWorkflow` | `frontend/src/core/composables/useWorkflowAction.ts`（定义于第 38 行，第 105 行导出） | 所在模块**被使用**（`TaskApprovalPool.vue`、`SafetyDiffCard.vue` 都 import 了 `useWorkflowAction`），但**只用到 `submitAudit` / `isSubmitting` / `notice`**，`resumeWorkflow` 本身零调用点 |
| `setToken` | `frontend/src/core/api/http.ts:56` | 零调用点（登录流程直接写 `localStorage`） |
| `clearToken` | `frontend/src/core/api/http.ts:61` | 零调用点 |
| `CardComponentProps` | `frontend/src/core/a2ui/types.ts:31` | 零引用 |
| `EMPTY_INPUT_MESSAGE` | `backend/app/api/v1/agent.py:59` | 零引用（后端实际用的是插件侧 `EMPTY_QUESTION_MESSAGE`） |

- **影响**：接口面虚胖，读者会误判存在未被接线的能力。
- **证据**：【实测】全仓库符号检索，只有定义点，无调用点。

### ⚪ L6 · 前端「运行追踪」面板恒为占位

- **落点**：`frontend/src/core/views/` 右侧抽屉的运行追踪区块
- **现象**：面板永远显示「暂无数据」，**没有对接 `ai_execution_traces` 的任何 API**（后端也**没有**提供查询 trace 的端点）。
- **影响**：即便后端补齐了状态机留痕（M4），前端也看不到；要打通需要**同时**补后端查询端点与前端渲染。
- **证据**：【实测】前端无 trace 相关 API 调用；后端 `api/v1/` 下无 trace 查询路由。

### ⚪ L7 · `ai_*` 四表零 ForeignKey

- **落点**：`backend/app/models/ai_schema.py`（`AIThreadMapping` / `AIChatMessage` / `AIExecutionTrace` / `AIKnowledgeBase`）
- **现象**：四张表**没有任何 `ForeignKey` 约束**，只有 `ai_thread_mappings.idempotency_key` 一条唯一约束。`ai_chat_messages.thread_id` 与 `ai_execution_traces.thread_id` 都不指向 `ai_thread_mappings.thread_id`。
- **影响**：引用完整性**完全靠应用层自觉**；删一条 thread 不会级联清消息，会留下孤儿数据。对本项目影响有限（弱引用本就是设计意图），但真实接入 OMS/SCADA 后，跨系统引用一旦物理化，缺约束会成为数据腐化的温床。
- **证据**：【源码】`ai_schema.py` 全文无 `ForeignKey` 声明。

---

## 5.5 文档漂移专节

> **本节是全文唯一允许出现失效符号的地方**，且每处都显式标注了"不存在 / 已废弃"。
> **列出的旧路径一律在当前工作区中不存在** —— 请勿再按它们去读代码。

### 5.5.1 蓝图文档（仓库根 122 KB 指南）描述的、**实际不存在**的文件

| 蓝图中的路径 | 现状 | 实际所在 |
|---|---|---|
| `app/core/config.py` | ❌ **不存在** | 配置散落在 `core/database.py`（`os.getenv`）+ `core/llm.py` + `core/rag/embeddings.py`，无统一配置中心 |
| `app/core/event_loop.py` | ❌ **不存在** | 事件循环策略切换**内联**在 `backend/main.py` 与 `backend/conftest.py` 顶部 |
| `app/core/workflow/bootstrap.py` | ❌ **不存在** | 装配逻辑内联在 `backend/main.py::lifespan` + `core/plugin/loader.py` |
| `app/core/workflow/resume.py` | ❌ **不存在** | 恢复逻辑在 `core/workflow/hitl.py::HITLController.resume_with_cas` |
| `app/core/policy/protocols.py` | ❌ **不存在** | ACL 契约在 `app/services/acl/protocols.py` |
| `app/core/acl/**` | ❌ **不存在** | 实际在 `app/services/acl/`（`iam_adapter.py` + `protocols.py`） |
| `app/core/rag/chunker.py` | ❌ **不存在** | 实际是 `app/core/rag/chunking.py`（`Chunker`） |
| `app/core/rag/evaluation/**` | ❌ **不存在** | 无检索评测模块 |
| `app/agent/`（整包） | ❌ **已整体删除** | 状态图改为**插件自治**：`app/plugins/power_grid/graph.py` |

### 5.5.2 `CLAUDE.md`（项目根）描述的、**实际不存在**的东西

| `CLAUDE.md` 中的描述 | 现状 |
|---|---|
| 核心状态图 `backend/app/agent/graph.py` | ❌ **不存在**（插件化重构后删除）；实际为 `backend/app/plugins/power_grid/graph.py` |
| 业务模式定义 `backend/app/schemas/dispatch.py` | ❌ **不存在**；实际为 `backend/app/plugins/power_grid/schemas.py`（且该文件是死代码，见 L4） |
| 状态类型 `PlanState` | ❌ **不存在**；实际为 `core/workflow/base_state.py::BaseWorkflowState`（5 字段 TypedDict）+ 插件自定义的 dict 状态 |
| 挂起点 `interrupt_before=['dispatcher_approval']` | ❌ **不存在**；实际是 `human_audit` 节点**内部**调用 `interrupt({...})`（`interrupt_before` 是节点级静态挂起，本项目用的是**节点内动态挂起**） |
| 检查点文件 `backend/power_dispatch.db`（SQLite） | ❌ **不存在**；实际是 **PostgreSQL** + `AsyncPostgresSaver`（`langgraph-checkpoint-postgres`） |
| `AsyncSqliteSaver` | ❌ **已废弃**；实际使用 `AsyncPostgresSaver`（`project-docs/overall-structure.md` 仍写 `AsyncSqliteSaver`，同样过时） |
| `checkpointer_pool` | ❌ **不存在**；`core/database.py` 的导出名是 **`checkpointer_manager`**（`CheckpointerManager` 实例，内部持有 `AsyncConnectionPool`） |
| 状态流转 `INIT → WAITING_DISPATCHER_REVIEW → PERMITTED / REJECTED` | ⚠️ **命名过时**；实际常量是 `DRAFT` / `WAITING_HUMAN` / `PERMITTED` / `REJECTED` / `SAFETY_REJECTED`（见 `core/workflow/thread_mapping_store.py` 与 `plugins/power_grid/constants.py`） |
| 调度令格式 `DISP_CMD_<YYYYMMDDHHMM>_<4位HEX大写>` | ❌ **格式不符**；实际是 `DISP-<YYYYMMDD>-<8位大写HEX>`（`plugins/power_grid/adapters/scada_adapter.py`） |
| **110kV/220kV/500kV+ 必须定级 `HIGH` 并强制挂起；10kV 定级 `LOW` 自动签发** | ❌ **完全未实现**；见 **H2**。当前高压与低压走完全相同的判定路径，且**所有**工单都无条件挂起人工核签。 |

### 5.5.3 `project-docs/overall-structure.md` 的过时点

| 描述 | 现状 |
|---|---|
| `AsyncSqliteSaver` | ❌ **已废弃** → 实际 `AsyncPostgresSaver` |
| SQLite 单文件存储 | ❌ **不存在** → 实际 PostgreSQL 14+（`pgvector/pgvector:pg16`）+ pgvector 扩展 0.8.7 |
| `app/core/acl/**` | ❌ **不存在** → 实际 `app/services/acl/**` |

### 5.5.4 处置建议

1. **以本文档为准**作为当前代码基线（本文档的每条断言都已逐行回对源文件或现场实测）。
2. 三个文档的更新优先级见 **第六章 P2-7**：`CLAUDE.md` 最高（它是 AI 助手的常驻上下文，错误的上下文会持续放大 H2 这类误解）。

---

# 第六章 后续优化与功能扩展路线图

> **排序原则**：先止血（把"静默失效"变成"显式失败"）→ 再补正确性（业务红线、状态机留痕、权限）→ 最后做工程化与体验。
> **每项格式**：现状 → 目标 → 改动落点（文件:函数）→ 验收标准。

## 6.0 路线图总览

| 优先级 | 主题 | 条目数 | 预计工作量 | 目标里程碑 |
|---|---|---|---|---|
| **P0** | 止血与合规红线 | 5 | 2~3 人日 | 下一轮迭代内完成 |
| **P1** | 正确性与工程化 | 11 | 6~9 人日 | 下一个版本 |
| **P2** | 体验与扩展 | 8 | 5~8 人日 | 持续推进 |

**依赖关系**：
- **P0-1（向量供应商）** 是 **P0-3（安规用真 RAG）** 的前置 —— 先把向量修好，再谈用召回结果。
- **P0-2（电压定级）** 必须在 **P0-3** 之后 —— 否则会用错误的规则去解释错误的召回。
- **P1-1（trace 覆盖）** 建议紧跟 P0 落地 —— 否则修复过程本身没有可观测性。

---

## 6.1 P0 · 止血与合规红线（5 项）

### P0-1 · 让向量降级从「静默」变成「显式」

| 项 | 内容 |
|---|---|
| **现状** | 供应商错配 → 裸 `ValueError` → MD5 伪向量 → 检索全失效，但 HTTP 响应毫无异常（M3 相关，H1） |
| **目标** | ① 配错时**启动即失败**或**每个响应都带降级标记**；② 伪向量永远不能被当成检索结果返回给用户 |
| **改动落点** | `backend/app/core/rag/embeddings.py`：`EmbeddingService.__init__` 增加 `self.degraded: bool`；`get_embeddings` 在走伪向量分支时置位<br>`backend/app/core/rag/vector_service.py::search_advanced`：命中伪向量时**抛异常或返回带 `degraded` 标记的结构**<br>`backend/app/api/v1/knowledge.py`：`search` / `ask` 响应增加 `degraded: bool` 字段；`backend/app/api/v1/knowledge.py` 的 `qa_llm` 改为**请求期构造**（同时解决 M11）<br>`backend/.env`：补齐 `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL`（与 `EMBEDDING_MODEL_NAME` **同源**） |
| **验收** | ① 故意写错端点 → `/knowledge/search` 返回 `degraded: true` 且**结果为空**（而不是返回噪声）；② 配对端点 → `degraded: false` 且默认阈值下能命中 `SMOKE-TEST-001`（见第四章 A.4） |

### P0-2 · 补齐电压等级风险定级

| 项 | 内容 |
|---|---|
| **现状** | 安规判定与电压等级无关，高压低压同路径（H2） |
| **目标** | `voltage_level → risk_level` 显式映射；`HIGH` 级强制人工核签且**不可被任何配置绕过** |
| **改动落点** | `backend/app/plugins/power_grid/constants.py`：新增 `VOLTAGE_RISK_MAP` 与 `RISK_LEVEL_HIGH` / `RISK_LEVEL_LOW` 常量（遵循"禁止魔法值"）<br>`backend/app/plugins/power_grid/graph.py::safety_check_node`：按 `state["voltage_level"]` 定级，把 `risk_level` 写入返回状态<br>`backend/app/plugins/power_grid/graph.py::route_after_safety_check`：**只有 `LOW` 级且无违规**才允许自动推进；`HIGH` 级一律进 `human_audit`<br>`backend/app/plugins/power_grid/router.py::apply_dispatch`：`card_payload` 增加 `risk_level` 字段 |
| **验收** | ① 110kV 缺安措 → 仍进人工核签池，`card.risk_level == 'HIGH'`；② 10kV 安措完备 → 走自动推进路径（需要先与业务方确认"自动签发"是否真要开放）；③ 500kV+ 与 10kV 的 `risk_level` 明确不同 |

> ⚠️ **前置确认**：当前实现**所有**工单都无条件进人工核签（HITL 熔断是"宁多勿少"）。改成按风险分级放行 10kV，属于**降低安全等级**的业务决策，**必须由业务方书面确认**后再实施。技术实现本身风险很低。

### P0-3 · 让安规判定真正使用 RAG 召回

| 项 | 内容 |
|---|---|
| **现状** | 召回结果被丢弃，安规判定实为两条关键词匹配（H3） |
| **目标** | 召回条款**参与**违规判定，并作为违规项的**出处依据** |
| **改动落点** | `backend/app/plugins/power_grid/graph.py::safety_check_node`：<br>① 把 `search_advanced(...)` 的返回值**赋给变量**；② `except` 里改为 `logger.warning` 并**不吞异常语义**（至少记进 violations 或状态）；③ 用召回内容的 `section_title` / `content` 构造 violations 文案，并附带 `doc_code` 出处<br>`backend/app/plugins/power_grid/graph.py`：violations 结构从 `list[str]` 升级为 `list[dict]`（含 `code` / `message` / `citation`）—— **注意：这是一次破坏性契约变更**，前端 `SafetyDiffCard.vue` 需同步 |
| **验收** | ① 召回为空时 violations 仍能给出**通用安规条款**（兜底），而不是"没查到就不判"；② 召回非空时每条 violation 都带 `doc_code` 出处，可与第四章 A.4 的断言对上 |

### P0-4 · 回写 `biz_order_id`

| 项 | 内容 |
|---|---|
| **现状** | `ai_thread_mappings.biz_order_id` 恒为 NULL（M1） |
| **目标** | 弱引用可查：一条 SQL 就能把本地工单对到真实 OMS 单 |
| **改动落点** | `backend/app/core/workflow/thread_mapping_store.py::ThreadMappingStore.create_mapping`：增加 `biz_order_id: str \| None = None` 形参<br>`backend/app/plugins/power_grid/router.py::apply_dispatch`：拿到 OMS 单号后补一次 UPDATE（建议新增 `ThreadMappingStore.update_biz_order_id(thread_id, biz_order_id)`）<br>注意：**OMS 单号在 `oms_draft` 节点内才生成**，晚于建档 ⇒ 建档时拿不到 ⇒ 必须在建档**之后**补写 |
| **验收** | DB 回读 `biz_order_id` 非空且与 `card_payload.biz_order_id` **完全一致**（见第四章 B.2 的回读断言） |

### P0-5 · 给 `GET /messages` 加归属校验

| 项 | 内容 |
|---|---|
| **现状** | 任意登录用户可读任意工单的消息流（M2） |
| **目标** | 只有**提报人本人**或**被指派的审批角色**能读该 thread 的消息 |
| **改动落点** | `backend/app/plugins/power_grid/router.py::list_thread_messages`：先 `ThreadMappingStore.get(thread_id)` 取 `creator_id` / `assigned_role`，再与 `current_user["sub"]` / `current_user["role"]` 比对；不匹配返回 **403**（或对非归属者返回空列表，与 `list_tasks` 保持一致） |
| **验收** | ① 提报员读自己建的 thread → 200；② 提报员读别人的 thread → 403 或空列表；③ 调度长读指派给自己的 thread → 200 |

---

## 6.2 P1 · 正确性与工程化（11 项）

| # | 主题 | 现状 → 目标 | 改动落点 | 验收标准 |
|---|---|---|---|---|
| **P1-1** | **状态机节点留痕** | 四个节点零 trace（M4）→ 每个节点一次 trace，`node_name` 可区分 | `backend/app/plugins/power_grid/graph.py`：四节点内注入 `trace_sink` 调用（`context.trace_sink.record(node_name=..., latency_ms=...)`） | DB 中一次工单产生 ≥ 4 行 trace，`node_name` 依次为 `safety_check` / `oms_draft` / `human_audit` / `issue_permit` |
| **P1-2** | **OMS 状态回写** | `update_order_status` 零调用（M3）→ 终态同步回 OMS | `backend/app/plugins/power_grid/router.py`：三个终态分支（`SAFETY_REJECTED` / `PERMITTED` / `REJECTED`）各补一次 `OMSGatewayAdapter.update_order_status(biz_order_id, status, opinion)` | 模拟 OMS 后，回写次数与终态一一对应 |
| **P1-3** | **`current_node` 指针回写** | 恒 NULL（M8）→ 可反查执行位置 | `backend/app/core/workflow/thread_mapping_store.py`：新增 `update_current_node(thread_id, node)`；在 `graph.py` 各节点入口调用 | DB 中 `current_node` 随流程推进而变化 |
| **P1-4** | **统一会话生命周期** | 14 处裸 `async with`（M6）→ 统一 `Depends(get_db_session)` | `backend/app/core/database.py::get_db_session`（启用）；`core/workflow/hitl.py`、`core/workflow/thread_mapping_store.py`、`core/workflow/message_recorder.py`、`core/rag/vector_service.py`、`plugins/power_grid/router.py` 逐个改造 | 全仓库 `AsyncSessionLocal()` 直接调用点归零 |
| **P1-5** | **SQL 日志按环境开关** | `echo=True` 硬编码（M5）→ 生产关闭 | `backend/app/core/database.py`：读 `DB_ECHO`（默认 `False`），开发 `.env` 里显式开 | 生产日志中不含业务明文 |
| **P1-6** | **打通 `action_payload` 回路** | 前端发、后端丢（M7）→ 卡片动作能被后端消费 | `backend/app/api/v1/agent.py::chat_stream`：读取 `req.action_payload` 并路由到插件 handler（需同步扩展 handler 签名或新增 `on_action` 钩子）；`backend/app/schemas/a2ui.py` 明确 `action_payload` 的结构契约 | 前端发一个 action_payload，后端日志可见且产生可观测行为 |
| **P1-7** | **测试资产入库** | `backend/tests/*` 被 gitignore（M12）→ 可 CI | `.gitignore`：移除 `backend/tests/*` 规则（或改为 `backend/tests/**/__pycache__/` 等精细规则） | 新克隆后 `pytest --collect-only` 能收集到 6 模块 / 16 用例 |
| **P1-8** | **修复两个压力脚本** | 必失败（M9）→ 可跑 | `backend/tests/stress_cas_concurrency.py`：`is_permitted` → `approved`；`backend/tests/verify_cas_manual.py`：`checkpointer_pool` → `checkpointer_manager` | `pytest tests/stress_cas_concurrency.py` 与 `pytest tests/verify_cas_manual.py` 均通过 |
| **P1-9** | **去掉硬编码断言** | `total == 2`（M10）→ 相对断言 | `backend/tests/test_pending_pool_filter.py::test_pool_count_unchanged`：改为"归档前后差值"断言 | 在任意待办池基数下都通过 |
| **P1-10** | **LLM 客户端改为请求期构造** | 模块级固化（M11）→ 可注入 | `backend/app/api/v1/knowledge.py`：`qa_llm` 改为函数内 `build_chat_model(temperature=0.1)`（配合 P0-1） | 关闭 Key 后 `/knowledge/ask` 稳定走降级分支；测试可 monkeypatch |
| **P1-11** | **`interrupt` 异常语义校准** | 现状可工作，但缺少契约测试 | `backend/tests/test_dispatch_workflow.py`：补一条"节点内 `interrupt` 抛异常"的用例，锁定 `langgraph` 升级后的行为 | langgraph 升级时该用例能第一时间报警 |

---

## 6.3 P2 · 体验与扩展（8 项）

| # | 主题 | 现状 → 目标 | 改动落点 | 验收标准 |
|---|---|---|---|---|
| **P2-1** | **前端引入 `vue-router` + `pinia`** | 手写状态（M14）→ 标准化 | `frontend/package.json` 加依赖；`frontend/src/core/workbench/useWorkbenchStore.ts` 迁为 Pinia store；新增路由层 | 页面可深链接；状态可 devtools 追踪 |
| **P2-2** | **前端测试基座** | 无测试（M14）→ 有 `vitest` | `frontend/package.json` 加 `vitest` / `@vue/test-utils` / `jsdom`；新增 `test` script；对 `useWorkbenchStore` 与 `agent.ts` 的事件分派写单测 | `npm run test` 可跑；`npm run build` 仍是交付门禁 |
| **P2-3** | **`/plugin/manifest` 加固** | 无鉴权（L1 相关）→ 有限保护 | `backend/app/api/v1/plugin.py`：**保留免鉴权**（前端启动必需），但**限制返回内容**（去掉 `identities` 里的敏感字段，或加签名/版本钉） | 未登录只能拿到 name/version/endpoints，拿不到身份目录 |
| **P2-4** | **「运行追踪」面板接真数据** | 恒为占位（L6）→ 可查 | 后端新增 `GET /api/v1/agent/traces?thread_id=`；前端 `frontend/src/core/views/` 的追踪区块改为拉取并渲染 | 完成一次工单后，面板显示节点序列与耗时 |
| **P2-5** | **知识库 un-delete + `content_hash` 修正** | 无恢复路径（L2）、哈希缺 `biz_tag`（L3） | `backend/app/core/rag/vector_service.py`：新增 `restore_document(doc_code)`；`backend/app/core/rag/chunking.py`：`content_hash` 纳入 `biz_tag`（**注意：会改变去重行为，需配套重灌存量**） | 软删可恢复；跨标签同文不再互相吞并 |
| **P2-6** | **清理死代码** | 5 处死导出 + 1 个死文件（L4、L5） | 删 `backend/app/plugins/power_grid/schemas.py`；删 `frontend/src/core/composables/useWorkflowAction.ts::resumeWorkflow`、`frontend/src/core/api/http.ts::setToken`/`clearToken`、`frontend/src/core/a2ui/types.ts::CardComponentProps`、`backend/app/api/v1/agent.py::EMPTY_INPUT_MESSAGE` | `npm run build` 通过；后端 import 无误 |
| **P2-7** | **文档对齐到当前实现** | 三份文档漂移（M13） | ① 项目根 `CLAUDE.md`：改写「项目背景与架构拓扑」与「业务红线」两节（尤其**电压定级**规则）；② 仓库根蓝图指南：标注为"历史蓝图"或按现状重写；③ `project-docs/overall-structure.md`：`AsyncSqliteSaver` → `AsyncPostgresSaver` | 新成员按 `CLAUDE.md` 能一次定位到真实文件；AI 助手上下文不再误导 |
| **P2-8** | **`ai_*` 四表补外键 + 接入 CI** | 零 FK（L7）、无 CI | `backend/app/models/ai_schema.py`：补 `ForeignKey("ai_thread_mappings.thread_id")`（需配套 Alembic 迁移）；`backend/scripts/check_plugin_isolation.py` 与 `pytest` 纳入 CI 流水线 | `alembic upgrade head` 成功；CI 绿灯 |

---

## 6.4 建议的落地节奏

```
里程碑 1（止血，1~2 天）
  ├─ P0-1 向量降级显式化 + 补齐 EMBEDDING_* 配置
  └─ 复跑第四章场景 A，确认 A.4 语义断言通过

里程碑 2（合规，2~3 天）
  ├─ P0-2 电压等级定级（需业务确认）
  ├─ P0-3 安规用真 RAG
  ├─ P0-4 biz_order_id 回写
  └─ P0-5 /messages 归属校验
  ⇒ 此时第四章的场景 B 才真正具备"业务意义"

里程碑 3（可观测，1 天）
  ├─ P1-1 状态机留痕
  ├─ P1-3 current_node 指针
  └─ P1-2 OMS 状态回写
  ⇒ 配合 P2-4，前端运行追踪面板才有内容

里程碑 4（工程化，3~4 天）
  ├─ P1-4 ~ P1-11（会话、SQL 日志、测试资产、脚本修复、LLM 注入）
  └─ P1-7 完成后再建 CI

里程碑 5（体验，持续）
  └─ P2-1 ~ P2-8
```

> 📌 **P0-1 必须最先做**：它是**唯一一个"不修就看不出问题"的项**。其余所有项在演示阶段都能糊过去，唯独向量降级会让整个 RAG 能力**静默失效**却毫无征兆 —— 而且它同时是 P0-3 的前置。

---

## 结语

本项目在**架构层面**已经完成了一次高质量的重构：从"单业务 Demo"进化到"通用底座 + 业务插件"的双层结构，物理隔离、依赖反转（`PluginManifest` / `PluginLoader` / `GraphRegistry`）、防腐层（`typing.Protocol`）、CAS 乐观锁、双连接池、A2UI 扁平协议、SSE 流式 —— 这些底座能力都**真实存在、可运行、有测试覆盖**。

当前最大的问题**不在架构**，而在于**"底座很稳，业务很薄"**：真正的电力安规语义（电压定级、规程条款判定、风险分级）尚未落到代码里，而**文档却在描述一个尚未实现的版本**。加上向量供应商错配导致的**静默降级**，三者叠加，让系统呈现出的"能跑"具有相当迷惑性。

建议按第六章的里程碑顺序推进：**先让失败可见（向量）→ 再让红线正确（定级 + 真 RAG）→ 再让过程可查（留痕）→ 最后补工程化**。

