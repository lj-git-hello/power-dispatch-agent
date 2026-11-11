# 企业级通用 AI Agent 通用脚手架 · 落地开发与架构全景指南

> **版本**：v2.0（A 级定稿）  ·  **性质**：生产级实施规约（Production-Ready Guideline）
> **v1.0 定位**：企业级通用 AI Agent 通用脚手架·落地开发与架构全景指南
> **本版说明**：v2.0 基于对 v1.0 的工业级审计逐条修订，完整对照见 **附录 A（审计问题 → 修订动作映射表）**。文中所有代码为可运行骨架，配置项一律外置。

---

## 目录

- [§0 阅读指南与适用范围](#0-阅读指南与适用范围)
- [§1 架构总原则与业务边界](#一架构总原则与业务边界)
- [§2 分层架构设计与职责边界](#二层架构设计与职责边界)
- [§3 数据底座：3+N 模型、双连接池与迁移](#三数据底座3n-模型双连接池与迁移)
- [§4 业务防渗透层（ACL）与网关通信桥](#四业务防渗透层acl与网关通信桥)
- [§5 LangGraph 状态机中枢与 HITL 人机协同](#五langgraph-状态机中枢与-hitl-人机协同)
- [§6 通用 RAG 底座：分块、版本化向量与检索](#六通用-rag-底座分块版本化向量与检索)
- [§7 前端通用工作台与 A2UI 动态卡片](#七前端通用工作台与-a2ui-动态卡片)
- [§8 多角色协同、CAS 乐观锁与运行治理](#八多角色协同cas-乐观锁与运行治理)
- [§9 前后端交互协议（HITL / SSE / A2UI 幂等）](#九前后端交互协议hitssea2ui-幂等)
- [§10 可观测性与成本治理](#十可观测性与成本治理)
- [§11 部署、迁移、灰度与回滚](#十一部署迁移灰度与回滚)
- [§12 测试策略](#十二测试策略)
- [§13 新业务插件接入 SOP](#十三新业务插件接入-sop)
- [§14 避坑红宝书](#十四避坑红宝书)
- [附录 A 审计 → 修订对照表](#附录-a审计--修订对照表)
- [附录 B 版本矩阵与环境变量清单](#附录-b版本矩阵与环境变量清单)

---

## 0. 阅读指南与适用范围

### 0.1 适用读者

| 角色 | 建议阅读顺序 | 关注点 |
|---|---|---|
| 架构师 | §1 → §2 → §3 → §9 → §11 | 分层边界、协议契约、迁移与回滚 |
| 高级后端 | §3 → §4 → §5 → §8 → §9 | 数据一致性、外部副作用、鉴权 |
| 高级前端 | §7 → §9 | 卡片幂等、离线合并、流式协议 |
| 安全 / 审计 | §1 → §4 → §8 → §10 | 资产边界、越权面、留痕完整性 |
| 运维 / SRE | §3 → §10 → §11 | 连接预算、迁移、灰度、熔断 |

### 0.2 本手册解决什么

提供一套**与业务无关**的 AI Agent 脚手架内核：会话与执行流解耦、确定性状态机托底、人机协同熔断、通用 RAG 检索、动态卡片交互面、多角色并发安全，以及与之配套的**协议契约**。业务方以插件形式接入，**不修改 core**。

### 0.3 本手册不解决什么

- 不提供业务主数据的定义与存储（那属于企业已有主数据系统）。
- 不替代 CA / IAM / OMS / SCADA 等外部系统的实现；本手册只定义**防腐层契约**。
- 不承诺模型零幻觉；本手册提供**依据可溯**的机制（条款检索 + 引用标注 + 人工熔断）。

### 0.4 强制约束（贯穿全文）

| 编号 | 约束 | 落地表现 |
|---|---|---|
| M1 | 凭据零硬编码 | 所有密钥/连接串走环境变量，缺失即启动失败 |
| M2 | 全链路纯异步 | Python 侧禁止在事件循环内调用阻塞方法 |
| M3 | 确定性优先 | 分支判定走强类型 Schema，不做自然语言字符串匹配 |
| M4 | 外部副作用可重入 | 一切跨系统写操作必须幂等且可重放 |
| M5 | 状态单一写入口 | 业务状态的终态只由状态机写回，不允许接口层直改 |
| M6 | 契约先于实现 | 新增协议必须先冻结事件/字段契约，再写代码 |

---

## 1. 架构总原则与业务边界

### 1.1 核心五公约（v2 修订：新增 M6「白名单扩展点公约」）

#### 公约 1：资产边界 —— AI 专属库严禁双写业务主数据

**规则**
- AI 库**不存储**权威业务主数据（用户账号主档、组织架构主档、业务主表）。
- 外部对象一律以 `biz_order_id` **引用**，不复制其业务字段。
- **唯一例外：审计快照（Audit Snapshot）**。为满足可追溯性，允许在 AI 库冗余「操作发生时的用户 ID / 部门 / 角色 / 时间戳」等**只读留痕快照**，并满足：
  - 快照字段在表上以 `*_snapshot` 或注释标注 `非权威数据`；
  - 快照**仅用于展示与审计**，任何业务判定（如管辖范围匹配）必须回源权威系统或以 `assigned_scope` 显式字段为准；
  - 快照**允许陈旧**，不得作为权限判定依据。

  > **v1.0 缺陷修正**：v1.0 一边宣称"严禁双写用户账号与组织架构"，一边在 `ai_thread_mappings` 中落了 `creator_id / creator_dept / creator_role`，构成自相矛盾。v2.0 显式承认"审计快照"这一合法例外并划死使用边界。

- **对话正文是双写的最大漏点**：`ai_chat_messages.content` 是自由文本落库区，用户粘贴的工单号、身份证号会被静默双写。v2.0 要求**落库前强制脱敏**（见 §10.3），并由脱敏器真实置位 `is_sanitized`，禁止把该字段当作"已完成脱敏"的装饰性标记。

#### 公约 2：物理隔离 —— 三条数据流分库分治

| 层 | 载体 | 用途 | 隔离目标 |
|---|---|---|---|
| 引擎层 | LangGraph Checkpointer（`checkpoints` / `checkpoint_blobs` / `checkpoint_writes`） | 节点恢复与断点续跑 | 高频小事务；**故障域不得传染业务侧** |
| 展示层 | `ai_chat_messages`（A2UI Snapshot） | 卡片重放、离线恢复、审计留痕 | 写放大可控；可被前端缓存比对 |
| 业务层 | ACL / API Gateway | 生命周期控制、组织权限、凭证签发 | **AI 库绝不直写业务系统** |

> **v1.0 表述修正**：v1.0 称双连接池用于"防止 LangGraph 高频读写冲突"——**因果错误**。两个池指向同一个库同一套表，Postgres 的锁与 WAL 争抢不会因连接池分离而消失。真实的隔离收益是三条：
> 1. **故障域隔离**：checkpointer 的慢事务 / 长事务不占用业务连接池，其连接耗尽不拖垮业务侧；
> 2. **事务语义隔离**：checkpointer 用 `autocommit=True` 独立连接，避免长事务持锁；
> 3. **连接预算隔离**：两类负载的池大小独立可调，容量规划可控。
>
> 规范中禁止再用"防止读写冲突"这类表述。

#### 公约 3：懒创建 —— 外部单据只在显式确认后签发

- 外部业务系统**绝不记录、不双写**。
- 仅当到达特定审批节点、且获得用户或授权人**显式确认**后，才由防渗透层向外部主系统签发业务单据。
- **落地要求（v1.0 缺陷修正）**：v1.0 定义了 `OrderGatewayProtocol.create_official_order`，但状态机中**从未有任何节点调用它**，导致 `biz_order_id` 恒为 `None`、签发链路断裂。v2.0 在 §5.3 补 `create_official_order` 节点，并在 §5.7 规定 `biz_order_id` 缺失时**必须 fail-closed（拒绝签发）**。

#### 公约 4：窗口与执行流解耦

- 前端 UI 窗口持有 `session_id`（本地缓存 + 手指会话）。
- 后端 LangGraph 执行流持有 `thread_id`。
- 一个交互窗口可诞生多个任务流；同一会话多次交互**互不阻塞**。
- **落地要求（v1.0 缺陷修正）**：v1.0 宣称"并发不阻塞"，但 `ai_chat_messages` 无任何顺序字段，并发插入的消息顺序不确定，前端渲染可能错乱。v2.0 引入会话内单调序号 `seq`（§3.3）与原子分配器（§10.2）。

#### 公约 5（新增）：白名单扩展点 —— Core 的唯一合法开口

core 保持 100% 业务中立，但必须为插件预留**唯一**合法开口，且该开口**显式、可枚举、可审计**：

| 扩展点 | 位置 | 白名单内容 |
|---|---|---|
| 插件装配清单 | `frontend/src/core/plugins/registry.ts` | 插件 ID → 卡片/表单/路由的显式注册表 |
| 插件清单 | `backend/app/core/plugin/manifest.py` | 插件 ID → 状态机工厂、路由前缀、策略实现的显式注册表 |
| 策略 SPI | `core/policy/protocols.py` | 风险分级、路由、管辖范围等业务判定的接口定义 |

> **v1.0 缺陷修正**：v1.0 目录树把 `App.vue # 插件装配入口` 放在 `core/` 下却未声明为例外，等于 core 直接 import 业务插件，隔离公约第一句即破。v2.0 将装配收敛到**独立的注册表文件**，core 只认识"插件 ID"而不认识具体插件实现；新增插件只改注册表一行，core 零改动，且注册表可被静态检查扫描（见 §12.3）。

### 1.2 系统总体架构拓扑

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      前端工作台（Universal Vue 3 Workbench）                      │
│  • 统一 JWT 网关 / 身份模拟开关            • 业务插件模式化外壳（会话 / 主视图 / 审批池）│
│  • 60Hz 渲染调度引擎（背压 + 可见性降级）   • A2UI 动态卡片分发器（按 card_id 复用）   │
│  • CAS 409 冲突裁决                        • IndexedDB 离线快照（带版本水位）           │
└──────────────────────────────────────────────────────────────────────────────────┘
                                    │ HTTP RESTful / SSE 单向推流
┌──────────────────────────────────────────────────────────────────────────────────┐
│                        FastAPI 通用 AI Agent 中枢网关                             │
│  [安全网关拦截层]  Authorization → JWT 解码 → { sub, roles, scopes, dept }          │
│  [多视图路由器]    会话流 (/sessions) 与 待办审批池 (/tasks) 物理隔离路由           │
│                                                                                   │
│  ┌────────────────────┐          ┌──────────────────────────────────────┐         │
│  │ 通用 RAG 检索/构建 │          │  LangGraph 异步状态机调度引擎          │         │
│  │ (core/rag/)        │          │  • 纯命令式节点恢复 (Command resume)   │         │
│  │ • 流式解析切片      │          │  • interrupt() 人机协同挂起断点       │         │
│  │ • 版本化向量与去重  │          │  • 状态机版本自增与 CAS 校验           │         │
│  │ • HNSW + 迭代扫描   │          │  • 独立只读消息快照提取节点           │         │
│  └────────────────────┘          └──────────────────────────────────────┘         │
│                                                                                   │
│  ┌────────────────────┐          ┌──────────────────────────────────────┐         │
│  │ 业务防渗透层 (ACL)  │          │  策略 SPI (core/policy/)               │         │
│  │ • IAMAdapter        │          │  • RiskPolicy（风险分级）             │         │
│  │ • OrderGateway      │          │  • DispatchPolicy（派单范围）          │         │
│  │ • CredentialGateway │          │  • 插件实现，核心仅定义接口           │         │
│  │ • 强类型防腐 + 失败即抛│         └──────────────────────────────────────┘         │
│  └────────────────────┘                                                             │
└──────────────────────────────────────────────────────────────────────────────────┘
                    │ HTTP / RPC                    │ TCP (5432)
┌───────────────────────────────────┐   ┌──────────────────────────────────────────┐
│      企业已有权威业务系统          │   │        AI 专属 PostgreSQL 16             │
│ (ERP / CRM / OMS / PMS / 统一身份)│   │  (pgvector ≥ 0.8，启用迭代扫描)          │
│ • 组织架构 / 人员主表 / 业务主数据 │   │  [引擎层] checkpoints / writes            │
│ • 权威流程引擎 / 传输审批流转      │   │  [调度业务] ai_thread_mappings           │
│ • AI 系统绝不改正主数据            │   │  [展示快照] ai_chat_messages              │
└───────────────────────────────────┘   │  [运行审计] ai_execution_traces           │
                                        │  [知识库] ai_knowledge_base (HNSW)        │
                                        └──────────────────────────────────────────┘
```

---

## 2. 分层架构设计与职责边界

### 2.1 目录拓扑（v2 修订）

```text
backend/                                    frontend/
├── app/                                    ├── src/
│   ├── core/           # 100% 业务中立内核    │   ├── core/           # 100% 业务中立内核
│   │   ├── event_loop.py   # 事件循环策略      │   │   ├── a2ui/       # 卡片注册与渲染宿主
│   │   ├── database.py     # 双连接池与生命周期│   │   ├── engine/     # 渲染调度/离线快照
│   │   ├── security.py     # JWT 解码与主体   │   │   ├── api/        # SSE 客户端/HTTP 拦截
│   │   ├── llm.py          # 统一模型适配与降级│   │   ├── composables/# CAS 裁决 Hook
│   │   ├── rag/            # 分块/切片/向量检索│   │   ├── workbench/  # 工作台共享 Store
│   │   ├── policy/         # 策略 SPI（跨业务） │   │   ├── views/      # 会话流/审批池
│   │   ├── plugin/         # 插件注册与隔离校验│   │   ├── plugins/    # 插件注册表（白名单）
│   │   ├── workflow/       # 状态机基类与检查点│   │   └── utils/      # Markdown 等
│   │   └── models/         # 3+N 数据模型     │   └── plugins/       # 业务插件目录
│   ├── models/           # ORM 模型（AI 库）   │       └── power_grid/  # 电网插件
│   ├── services/acl/     # 防渗透层（通用治理） │           ├── cards/   # 专属 A2UI 卡片
│   ├── schemas/          # 强类型出入参        │           ├── forms/   # 业务表单
│   ├── api/v1/           # 通用检索与插件端点  │           └── plugin.ts
│   └── plugins/          # 业务插件目录        └── App.vue              # 仅挂载 core 根组件
│       └── power_grid/                        │
│           ├── plugin.py   # 插件装配入口      │
│           ├── graph.py    # 状态机节点        │
│           ├── router.py   # 业务路由          │
│           ├── policy.py   # 风险/派单策略实现  │
│           └── adapters/   # OMS/SCADA 适配器  │
```

### 2.2 职责边界对照表（v2 修订）

| 模块分类 | 必属目录 | 允许包含的内容 | **绝对禁止**的行为 |
|---|---|---|---|
| **通用数据底座** | `core/database.py` | 连接池、生命周期、事务边界 | 业务表名、业务条件、硬编码凭据 |
| **通用 RAG 底座** | `core/rag/` | 分块、切片、向量检索、评测 | 写死业务术语、业务表结构、业务字段码 |
| **防渗透层** | `services/acl/` | Protocol、防腐、强类型校验、失败即抛 | 直接写业务库、返回 `dict`、静默回落到 Mock |
| **策略 SPI** | `core/policy/` | 接口定义、默认兜底策略 | **具体业务规则**（如"220kV 即高风险"） |
| **通用前端库** | `frontend/src/core/` | 卡片宿主、渲染引擎、离线缓存、CAS | 出现业务专有字段（电压等级、站点 ID 等） |
| **插件装配** | `core/plugin/`、`core/plugins/registry.ts` | 仅存插件 ID → 实现 的注册表 | 直接 import 业务插件实现 |
| **业务插件** | `plugins/<biz>/` | 状态机节点、专属卡片、业务路由表 | 修改 `core/` 下任何文件 |

> **v1.0 缺陷修正（分类灰区）**：v1.0 把 `services/acl/` 放在 `app/` 根下——既不在 `core/`（非中立内核）也不在 `plugins/`（非业务），落在架构分类的灰色地带，且含 OMS/SCADA 领域语义。v2.0 的切分是：
> - **通用治理能力**（Protocol 定义、防腐、强类型校验、Mock 契约、失败策略）→ `core/acl/`；
> - **业务领域适配**（OMS/SCADA 具体实现）→ `plugins/<biz>/adapters/`。
>
> 这样"通用内核复用"才真正成立：换一个业务域，ACL 治理逻辑零改动。

---

## 3. 数据底座：3+N 模型、双连接池与迁移

### 3.1 配置与凭据（M1：零硬编码）

```python
# backend/app/core/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


class ConfigurationError(RuntimeError):
    """配置缺失或不合法。生产环境必须 fail-fast，禁止静默回落到默认值。"""


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str                 # dev | staging | prod
    pg_async_uri: str            # SQLAlchemy(asyncpg) 连接串
    pg_psycopg_uri: str          # psycopg 连接串（checkpointer 专用）
    pg_pool_size: int
    pg_max_overflow: int
    checkpointer_pool_size: int
    enterprise_order_gateway_url: str | None
    enterprise_iam_gateway_url: str | None
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embedding_model: str
    embedding_dim: int
    autopilot_enabled: bool      # kill switch，见 §8.6

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise ConfigurationError(
            f"缺少必需环境变量 {name}。禁止使用默认凭据兜底，请检查 .env 或部署配置。"
        )
    return value.strip()


def _optional(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "dev").strip().lower()
    if app_env not in {"dev", "staging", "prod"}:
        raise ConfigurationError(f"APP_ENV 非法：{app_env}")

    order_gateway = _optional("ENTERPRISE_ORDER_GATEWAY_URL")
    iam_gateway = _optional("ENTERPRISE_IAM_GATEWAY_URL")

    # 生产环境的关键下游必须显式配置，缺失即阻断启动。
    if app_env == "prod":
        if not order_gateway:
            raise ConfigurationError(
                "生产环境必须配置 ENTERPRISE_ORDER_GATEWAY_URL。"
                "禁止回落 Mock 适配器——防腐层'沉默地失效'是比报错更危险的状态。"
            )
        if not iam_gateway:
            raise ConfigurationError("生产环境必须配置 ENTERPRISE_IAM_GATEWAY_URL。")

    return Settings(
        app_env=app_env,
        pg_async_uri=_require("PG_ASYNC_URI"),
        pg_psycopg_uri=_require("PG_PSYCOPG_URI"),
        pg_pool_size=int(os.getenv("PG_POOL_SIZE", "20")),
        pg_max_overflow=int(os.getenv("PG_MAX_OVERFLOW", "10")),
        checkpointer_pool_size=int(os.getenv("CHECKPOINTER_POOL_SIZE", "20")),
        enterprise_order_gateway_url=order_gateway,
        enterprise_iam_gateway_url=iam_gateway,
        llm_base_url=_require("LLM_BASE_URL"),
        llm_api_key=_require("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-v3"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "1536")),
        autopilot_enabled=os.getenv("AI_AUTOPILOT_ENABLED", "true").strip().lower() == "true",
    )
```

> **v1.0 缺陷修正**：v1.0 直接在 `database.py` 里硬编码
> `postgresql+asyncpg://ai_admin:ai_secure_2026@127.0.0.1:5432/agent_prod_db`。
> 该行同时踩中三个问题：明文生产凭据入库、库名标注为 `prod` 却连回环地址、手册自身在 §4 宣称"走环境变量"却在此处裸写。v2.0 全部收口到 `config.py`，**缺失即启动失败**。

`.env.example`（**提交进 Git，`.env` 本身必须进 `.gitignore`**）：

```dotenv
# ---- 运行环境 ----
APP_ENV=dev

# ---- 数据库（AI 专属库，禁止复用业务主库）----
PG_ASYNC_URI=postgresql+asyncpg://ai_user:CHANGE_ME@127.0.0.1:5432/agent_ai_db
PG_PSYCOPG_URI=postgresql://ai_user:CHANGE_ME@127.0.0.1:5432/agent_ai_db
PG_POOL_SIZE=20
PG_MAX_OVERFLOW=10
CHECKPOINTER_POOL_SIZE=20

# ---- 企业下游网关 ----
ENTERPRISE_ORDER_GATEWAY_URL=
ENTERPRISE_IAM_GATEWAY_URL=

# ---- 模型服务 ----
LLM_BASE_URL=https://your-llm-endpoint/v1
LLM_API_KEY=CHANGE_ME
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIM=1536

# ---- 运行治理 ----
AI_AUTOPILOT_ENABLED=true
```

### 3.2 双连接池与生命周期（v1.0 缺陷修正：补 `open()` / `close()`）

```python
# backend/app/core/database.py
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

# 1) 业务 ORM 连接池：asyncpg + SQLAlchemy
async_engine: AsyncEngine = create_async_engine(
    _settings.pg_async_uri,
    pool_size=_settings.pg_pool_size,
    max_overflow=_settings.pg_max_overflow,
    pool_recycle=1800,
    pool_pre_ping=True,
    pool_timeout=10,
    echo=False,
)
AsyncSessionLocal = async_sessionmaker(
    async_engine, expire_on_commit=False, class_=AsyncSession
)

# 2) LangGraph 检查点专用连接池：psycopg + autocommit，物理独立于业务池
#    psycopg-pool 3.2+ 池创建即为「关闭态」，必须显式 await open()
checkpointer_pool = AsyncConnectionPool(
    conninfo=_settings.pg_psycopg_uri,
    max_size=_settings.checkpointer_pool_size,
    open=False,                       # 显式声明，交由 lifespan 打开
    kwargs={"autocommit": True},      # 禁止长事务持锁，缩短故障占用窗口
    timeout=10,
    max_idle=300,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求级会话，请求结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def lifespan_resources() -> AsyncIterator[None]:
    """应用级资源生命周期：启动开、退出关。"""
    await checkpointer_pool.open()
    await checkpointer_pool.wait()
    try:
        yield
    finally:
        await checkpointer_pool.close()
        await async_engine.dispose()
```

> **v1.0 缺陷修正**：v1.0 创建 `AsyncConnectionPool` 后**既无 `await pool.open()` 也无 `await pool.close()`**。前者导致池处于关闭态、代码不可运行；后者导致进程退出时连接泄漏与告警。v2.0 把生命周期挂进 FastAPI `lifespan`，并在 `main.py` 中组装。

**事件循环策略（作用域收敛 + 真实理由）**

```python
# backend/app/core/event_loop.py —— 必须在任何事件循环创建前被导入
import sys
import asyncio

if sys.platform == "win32":
    # 真实理由：asyncpg 在 Windows 上依赖 loop.add_reader/add_writer，
    # 必须使用 Selector 事件循环；Proactor 不兼容。
    # 代价：放弃 Proactor 的 subprocess 与 add_signal_handler 能力。
    # 因此本模块必须最先导入（见 main.py 顶部），且不得被其他模块提前触发。
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

> **v1.0 缺陷修正（两处）**：
> 1. **理由缺失**：v1.0 只写了一句无解释的策略设置，未说明它是为 asyncpg 而设；读者会误以为是性能调优。
> 2. **作用域失控**：v1.0 把它塞在 `database.py` 里，而 `database.py` 会被任意模块 import——策略是**进程级全局副作用**，一旦 import 顺序变化就静默失效，且无法在测试中撤销。v2.0 抽成独立模块并在 `main.py` 第一行导入。
>
> **遗留风险（必须记录）**：该策略 API 在 Python 3.14+ 已进入弃用周期。迁移计划：升级到 3.14+ 时，改用显式 `--loop asyncio` + 在 `main.py` 中以 `asyncio.Runner`/`uvloop`（非 Windows）替代策略切换，并在 CI 中加入 Windows 启动冒烟用例。

**连接预算（容量规划，防止打满 PG `max_connections`）**

| 用途 | 池大小 | 溢出 | 小计 |
|---|---|---|---|
| 业务 ORM（asyncpg） | 20 | +10 | 30 |
| Checkpointer（psycopg） | 20 | 0 | 20 |
| Alembic / 运维脚本 | 2 | 0 | 2 |
| **AI 库合计** | — | — | **52** |

要求 `agent_ai_db` 所在实例的 `max_connections ≥ 80`（预留 50% 余量给监控、备份、临时排障连接），并在启动自检中校验。

### 3.3 "3+N" 数据模型（v2 修订：补约束、补状态机、补快照水位）

#### 核心 1：会话与执行流映射（Thread Mapping）

```python
# backend/app/models/ai_schema.py
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """统一使用带时区的 UTC 时间。禁止使用已弃用的 datetime.utcnow()。"""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AIThreadMapping(Base):
    """会话与执行流映射 + 业务调度主表。

    状态语义（唯一状态机写入，见 §5.7）：
      DRAFT ──提交──▶ SUBMITTED ──判定──┬─▶ WAITING_HUMAN ──审批──▶ APPROVING ─┬─▶ PERMITTED
                                        │                                        └─▶ REJECTED
                                        └─(低风险自动)──▶ APPROVING ──▶ PERMITTED
    APPROVING 可因外部副作用失败回落为 FAILED；WAITING_HUMAN 超时转 EXPIRED。
    """

    __tablename__ = "ai_thread_mappings"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    biz_order_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    # 幂等键：作用于**外部副作用**（建单、签发），不是会话行本身
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    # —— 审计快照（非权威数据，允许陈旧，禁止用于权限判定）——
    creator_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    creator_dept_snapshot: Mapped[str | None] = mapped_column(String(64))
    creator_role_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)

    # —— 派单目标：角色 + 管辖范围（双维度）——
    assigned_role: Mapped[str] = mapped_column(String(32), index=True, default="APPLICANT")
    assigned_scope: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    status: Mapped[str] = mapped_column(String(32), index=True, default="DRAFT")
    current_node: Mapped[str | None] = mapped_column(String(64))

    # —— 并发与审计 ——
    lock_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    operator_id: Mapped[str | None] = mapped_column(String(64))
    audit_opinion: Mapped[str | None] = mapped_column(Text)
    signature_hash: Mapped[str | None] = mapped_column(String(128))

    # —— 生命周期 ——
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # 消息序号的原子分配器（会话内单调，见 §10.2）
    next_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        Index("ix_thread_session_status", "session_id", "status"),
        # 同一会话内终态工单唯一，防止重复提交产生多条可审批记录
        Index("uq_session_biz_order", "session_id", "biz_order_id", unique=True,
              postgresql_where="biz_order_id IS NOT NULL"),
    )
```

> **v1.0 缺陷修正（逐条）**：
> | v1.0 问题 | v2.0 修正 |
> |---|---|
> | `datetime.utcnow`（naive、已弃用） | `utcnow()` + `DateTime(timezone=True)`，避免本地时区差 8 小时 |
> | `lock_version` 有 `default=1` 无 `server_default` | 补 `server_default="1"`，避免原生 SQL 插入 NULL 致条件恒不成立、永久 409 |
> | 状态枚举只有 4 个，CAS 却写入 `'RUNNING'` | 统一为 7 态，明确迁移路径；`'RUNNING'` 废除 |
> | 无终态回写路径（`PERMITTED/REJECTED` 永不写入） | §5.7 规定终态唯一写入口 |
> | `audit_opinion` / `signature_hash` / `current_node` 无落库路径 | 由 `finalize` 节点统一落库 |
> | `assigned_role` 无写入路径（人审任务永远进不了审批池） | §5.6 `dispatch_to_human` 节点写入 |
> | 派单只有角色维度 | 补 `assigned_scope`（管辖范围）双维度 |
> | 无 `expires_at`（挂起任务永不过期） | 补超时字段，配合 §8.5 超时收敛 |
> | 无消息序号 | 补 `next_seq` 原子分配器 |

#### 核心 2：展示快照（A2UI Snapshot）

```python
class AIChatMessage(Base):
    """A2UI 消息快照。既供前端渲染，也供审计与离线恢复。"""

    __tablename__ = "ai_chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # 会话内单调序号，由 ai_thread_mappings.next_seq 原子分配
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    role: Mapped[str] = mapped_column(String(16), nullable=False)   # user/assistant/system/tool
    kind: Mapped[str] = mapped_column(String(16), default="text")    # text/card/interrupt/error
    content: Mapped[str | None] = mapped_column(Text)

    # —— 卡片幂等与版本（v1.0 完全缺失，导致流式重复渲染与历史回放崩溃）——
    card_id: Mapped[str | None] = mapped_column(String(64))        # 逻辑卡片标识，跨帧稳定
    card_revision: Mapped[int] = mapped_column(Integer, default=0)  # 递增修订号，幂等 upsert 依据
    card_type: Mapped[str | None] = mapped_column(String(64))      # 卡片渲染器类型
    card_version: Mapped[str] = mapped_column(String(16), default="v1")  # 卡片契约版本
    card_payload: Mapped[dict | None] = mapped_column(JSONB)

    is_sanitized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # 幂等 upsert 的硬保证：同一逻辑卡片在同一修订号只能存在一行
        Index("uq_thread_card_rev", "thread_id", "card_id", "card_revision", unique=True,
              postgresql_where="card_id IS NOT NULL"),
        Index("ix_thread_seq", "thread_id", "seq"),
    )
```

> **v1.0 缺陷修正**：v1.0 的 `AIChatMessage` 没有 `card_id` / `card_revision` / `card_version` / `seq` / `updated_at`。后果有三：
> 1. **流式重复渲染**：同一张卡片的第 N 帧没有稳定标识，前端只能追加渲染 → 屏幕上出现 N 张重复卡片；
> 2. **历史回放崩溃**：卡片契约升级后，旧快照用新渲染器回放，结构不兼容即炸；
> 3. **离线合并无水位**：前端 IndexedDB 与服务端快照冲突时，没有可比较的版本，无法做 Last-Write-Wins。

#### 核心 3：运行审计（Execution Trace）

```python
class AIExecutionTrace(Base):
    """单次 LLM 调用 / 工具调用的运行审计。v1.0 定义了表但无埋点，本版补齐写入路径（§10.1）。"""

    __tablename__ = "ai_execution_traces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 注意：Numeric 列在 SQLAlchemy 中返回 Decimal，标注必须与之一致
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    tool_calls: Mapped[dict | None] = mapped_column(JSONB)
    error_log: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

#### 核心 4：知识库（版本化向量，v1.0 缺陷修正）

```python
class AIKnowledgeBase(Base):
    """向量知识库。

    v1.0 缺陷：维度硬编码 Vector(1536)，且无 embedding 模型/版本标识。
    后果：更换嵌入模型后，新旧向量在同一列静默混存，检索结果"看起来正常"实则错误。
    v2.0 引入 embedding_model / embedding_dim / embedding_version 三元组，
    换模型走「新列或新表 + 双写灰度 + 原子切换」，禁止原地覆盖。
    """

    __tablename__ = "ai_knowledge_base"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    biz_tag: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, nullable=False)

    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(32), nullable=False, server_default="v1")
    content_md5: Mapped[str] = mapped_column(String(32), index=True, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    doc_version: Mapped[str] = mapped_column(String(32), default="v1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index(
            "idx_knowledge_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("uq_doc_section_embedding", "doc_code", "section_title", "embedding_version",
              unique=True),
    )
```

> **换模型 SOP**：新增 `embedding_version=v2` → 灌入新向量 → 灰度检索同时查两版并按版本加权 → 验证召回率达标 → 原子切换应用层默认版本 → 回收 v1。禁止 `UPDATE ... SET embedding = ...` 原地覆盖。

### 3.4 迁移与初始化（v1.0 完全缺失）

v1.0 没有迁移方案、没有 `CREATE EXTENSION`、没有 checkpointer 建表、没提 HNSW 在线建索引。按 v1.0 落地会直接报 `relation "checkpoints" does not exist`。

**初始化顺序（幂等，可重复执行）**

```python
# backend/app/core/workflow/bootstrap.py
from sqlalchemy import text
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


async def ensure_database_ready(engine) -> None:
    """启动期自检：扩展、checkpointer 表、关键索引。失败即阻断启动。"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # checkpointer 建表（幂等，含内部 migration 表）
    saver = AsyncPostgresSaver(checkpointer_pool)
    await saver.setup()


async def set_vector_search_knobs(session) -> None:
    """带过滤条件的 HNSW 检索必须开启迭代扫描，否则 top_k 可能召回不足甚至为 0。"""
    await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
```

**Alembic 规范**

- 目录：`backend/alembic/`，`env.py` 走异步引擎（`async_engine_from_config` + `run_async_migrations`）。
- **HNSW 索引必须在线建**（`CREATE INDEX CONCURRENTLY`），在 Alembic 中需 `op.get_context().autocommit_block()`，否则建索引期间锁表，业务侧全量写入阻塞。
- 建索引前调 `maintenance_work_mem`（如 `256MB`）与 `max_parallel_maintenance_workers`，降低构建失败率。
- 迁移脚本必须**双向可回滚**；破坏性变更一律"加列 → 双写 → 切读 → 删列"四步走，禁止单步 DROP。

---

## 4. 业务防渗透层（ACL）与网关通信桥

### 4.1 协议定义（强类型返回，禁止 `dict`）

```python
# backend/app/core/acl/protocols.py
from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OfficialOrderStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class InternalUser(BaseModel):
    """来自权威 IAM 的用户主体。字段与组织架构主档一一对应，禁止 AI 库另存权威副本。"""

    model_config = ConfigDict(frozen=True)

    user_id: str
    name: str
    role: str
    department: str
    scopes: tuple[str, ...] = ()      # 管辖范围标识，用于工单归属校验
    roles: tuple[str, ...] = ()       # 多角色（如既是申报员又是调度员）


class OfficialOrderResult(BaseModel):
    """外部工单。字段用强类型承载，外部返回的任意字符串由 validator 拦截。"""

    model_config = ConfigDict(frozen=True)

    biz_order_id: str = Field(min_length=1)
    status: OfficialOrderStatus
    raw_payload: dict = Field(default_factory=dict)


class OfficialPermit(BaseModel):
    """外部签发的许可凭证。ca_signature_hash 是两票存档的法定要素，不可为空。"""

    model_config = ConfigDict(frozen=True)

    permit_no: str = Field(min_length=1)
    ca_signature_hash: str = Field(min_length=16)
    issued_at: datetime
    operator_id: str


@runtime_checkable
class IAMAdapterProtocol(Protocol):
    """注意：v1.0 定义为同步 verify_token，若生产 IAM 需远程校验会阻塞事件循环。
    v2.0 统一为 async，全链路纯异步（M2）。"""

    @staticmethod
    async def verify_token(token: str) -> InternalUser: ...


@runtime_checkable
class OrderGatewayProtocol(Protocol):
    @staticmethod
    async def create_official_order(
        draft_data: dict, creator_id: str, idempotency_key: str
    ) -> OfficialOrderResult: ...

    @staticmethod
    async def update_order_status(
        biz_order_id: str, new_status: str, opinion: str | None = None
    ) -> bool: ...


@runtime_checkable
class CredentialGatewayProtocol(Protocol):
    @staticmethod
    async def issue_official_permit(
        biz_order_id: str, operator_id: str, idempotency_key: str
    ) -> OfficialPermit: ...
```

### 4.2 双适配器实现（v1.0 缺陷修正：强类型防腐 + 失败即抛）

```python
# backend/app/core/acl/adapters/order_gateway.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import httpx

from app.core.acl.protocols import OfficialOrderResult, OfficialOrderStatus
from app.core.config import Settings, get_settings


class OrderGatewayError(RuntimeError):
    """外部网关不可用或返回不合法数据。禁止降级为 Mock。"""


class OrderGatewayAdapter:
    """生产适配器。Mock 适配器仅在 dev 环境显式装配。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def _gateway_url(self) -> str:
        # 调用时读取，而非类属性 import 时求值——便于测试注入
        url = self._settings.enterprise_order_gateway_url
        if not url:
            raise OrderGatewayError(
                "企业工单网关未配置。生产环境禁止回落 Mock（防腐层沉默失效比报错更危险）。"
            )
        return url

    @staticmethod
    async def create_official_order(
        draft_data: dict, creator_id: str, idempotency_key: str
    ) -> OfficialOrderResult:
        """v1.0 缺陷修正：
        1. 增加 idempotency_key 透传，满足 M4（外部副作用可重入）；
        2. 返回值改用 Pydantic 强类型，外部脏数据在边界被拦截；
        3. Mock 回落改为显式环境判定，prod 下必然失败。
        """
        settings = get_settings()
        if settings.app_env != "prod":
            return _mock_order(draft_data, creator_id)

        payload = {
            "draft": draft_data,
            "creator_id": creator_id,
            "idempotency_key": idempotency_key,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.enterprise_order_gateway_url}/api/v1/orders",
                    json=payload,
                    headers={"Idempotency-Key": idempotency_key},
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise OrderGatewayError(f"工单网关调用失败：{exc}") from exc

        # 强类型校验：外部返回的 status 非法直接拒绝，不进状态机分支
        try:
            return OfficialOrderResult.model_validate({
                "biz_order_id": body["order_no"],
                "status": body["status"],
                "raw_payload": body,
            })
        except Exception as exc:
            raise OrderGatewayError(f"工单网关返回不合法：{body!r}") from exc
```

```python
def _mock_order(draft_data: dict, creator_id: str) -> OfficialOrderResult:
    """仅用于本地开发与自动化测试。生产路径不可达。"""
    seed = f"{creator_id}:{json.dumps(draft_data, sort_keys=True, ensure_ascii=False)}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:6].upper()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return OfficialOrderResult(
        biz_order_id=f"MOCK-OMS-{stamp}-{digest}",
        status=OfficialOrderStatus.PENDING_REVIEW,
        raw_payload={"mock": True},
    )
```

> **v1.0 缺陷修正（三处致命）**：
> | v1.0 写法 | 后果 | v2.0 修正 |
> |---|---|---|
> | `if cls._GATEWAY_URL:` 不成立即返回 Mock | 生产漏配 env → **AI 拿着一张不存在的工单号去签发许可令**，且日志无痕 | prod 缺配置直接 `raise`；Mock 仅 dev 可达 |
> | `data["order_no"]` / `data["status"]` 裸索引 | 外部缺 key → KeyError → 500；外部返回任意字符串直接进状态机分支 | `model_validate` + `OfficialOrderStatus` 枚举校验 |
> | 无幂等键透传 | 重试即重复建单 | 幂等键走 header + body 双通道 |

### 4.3 IAM 适配器（同步改异步）

```python
# backend/app/core/acl/adapters/iam_adapter.py
import jwt
from jwt import InvalidTokenError

from app.core.acl.protocols import InternalUser
from app.core.config import get_settings


class IAMAdapter:
    """本地 JWT 校验 + 权威 IAM 装载组织/角色信息。"""

    @staticmethod
    async def verify_token(token: str) -> InternalUser:
        settings = get_settings()
        secret = settings.llm_api_key  # 仅示意：实际应独立配置 IAM_JWT_SECRET
        try:
            claims = jwt.decode(token, secret, algorithms=["HS256"], options={
                "require": ["sub", "exp", "roles"],
            })
        except InvalidTokenError as exc:
            raise PermissionError("无效的身份令牌") from exc

        # 组织与角色以权威 IAM 为准，AI 库只做快照留痕
        return InternalUser(
            user_id=claims["sub"],
            name=claims.get("name", claims["sub"]),
            role=claims["roles"][0] if claims.get("roles") else "UNKNOWN",
            roles=tuple(claims.get("roles", ())),
            department=claims.get("dept", ""),
            scopes=tuple(claims.get("scopes", ())),
        )
```

> **v1.0 缺陷修正**：v1.0 的 `verify_token` 是同步 `@staticmethod`。一旦生产 IAM 需要远程校验（查用户是否在岗、是否在管辖范围内），同步方法在 FastAPI 异步端点内会**阻塞事件循环**，违反 M2。v2.0 统一 `async def`。

---

## 5. LangGraph 状态机中枢与 HITL 人机协同

### 5.1 状态定义

```python
# backend/app/plugins/<biz>/schemas.py（或 core 的通用基类）
from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


class WorkflowState(TypedDict, total=False):
    # —— 标识 ——
    thread_id: str
    session_id: str
    creator_id: str
    creator_roles: list[str]
    creator_scopes: list[str]

    # —— 业务草稿 ——
    draft: dict[str, Any]

    # —— 外部引用 ——
    biz_order_id: str | None
    idempotency_key: str | None

    # —— 安规判定 ——
    risk_level: Literal["LOW", "HIGH", "UNKNOWN"]
    violations: list[dict[str, Any]]
    citations: list[dict[str, Any]]

    # —— 人审 ——
    requires_human: bool
    human_decision: dict[str, Any] | None

    # —— 终态 ——
    is_permitted: bool
    audit_opinion: str
    reviewer_id: str | None
    ca_signature_hash: str | None
    final_status: str | None
```

### 5.2 策略 SPI（v1.0 缺陷修正：风险分级不得硬编码在核心里）

v1.0 把"110kV/220kV/500kV 即高风险"写进了核心理念。后果：新增业务或新增电压等级就必须改 core，**直接违反公约 1 与公约 5**。v2.0 把判定下沉为插件策略，核心只定义接口。

```python
# backend/app/core/policy/protocols.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RiskClassification(BaseModel):
    risk_level: Literal["LOW", "HIGH", "UNKNOWN"]
    requires_human: bool
    reason: str
    matched_rules: list[str] = Field(default_factory=list)


class DispatchTarget(BaseModel):
    """人审派单目标：角色 + 管辖范围双维度。"""

    assigned_role: str
    assigned_scope: str | None = None


@runtime_checkable
class RiskPolicyProtocol(Protocol):
    async def classify(self, draft: dict) -> RiskClassification: ...


@runtime_checkable
class DispatchPolicyProtocol(Protocol):
    async def resolve_target(self, draft: dict, classification: RiskClassification) -> DispatchTarget: ...
```

插件侧实现（电网插件）：

```python
# backend/app/plugins/power_grid/policy.py
HIGH_RISK_KV: frozenset[int] = frozenset({110, 220, 500, 750, 1000})
LOW_RISK_MAX_KV: int = 35


class PowerGridRiskPolicy:
    """电网风险分级策略。规则全部外置，core 不感知电压等级。"""

    async def classify(self, draft: dict) -> RiskClassification:
        kv = _extract_kv(draft)
        if kv is None:
            return RiskClassification(
                risk_level="UNKNOWN", requires_human=True,
                reason="未能识别电压等级，按保守原则转人工核签",
            )
        if kv in HIGH_RISK_KV or kv >= HIGH_RISK_KV and kv > LOW_RISK_MAX_KV:
            return RiskClassification(
                risk_level="HIGH", requires_human=True,
                reason=f"{kv}kV 属于高压及以上电网检修，必须人工核签",
                matched_rules=[f"VOLTAGE_GE_{kv}"],
            )
        return RiskClassification(
            risk_level="LOW", requires_human=False,
            reason=f"{kv}kV 常规检修，安策完备条件下可自动签发",
            matched_rules=[f"VOLTAGE_LE_{LOW_RISK_MAX_KV}"],
        )
```

> **v1.0 缺陷修正**：v1.0 的分级规则写死在核心注释里。若平台同时接入第二个业务域（如同一框架做政务值班），就得改 core 状态机，破坏隔离公约。v2.0 后：新增业务域 = 新增插件 + 注册一行，core 零改动。

### 5.3 状态机全链路（v1.0 缺陷修正：补齐断链节点）

```mermaid
flowchart LR
    A[create_official_order<br/>创建外部正式工单] --> B[safety_review<br/>安规判定 RAG+LLM]
    B --> C{route_by_risk<br/>策略路由}
    C -->|requires_human| D[dispatch_to_human<br/>写 assigned_role/scope]
    D --> E[human_gate<br/>interrupt 挂起]
    E --> F{Command resume}
    F -->|approve| G[issue_permit<br/>外部签发许可令]
    F -->|reject| H[reject_order<br/>外部置 REJECTED]
    G --> I[finalize<br/>终态唯一写入口]
    H --> I
    C -->|低风险自动| G
```

#### 节点 1：`create_official_order`（**v1.0 缺失节点，闭环断点 1**）

```python
async def create_official_order_node(state: WorkflowState, deps: Deps) -> dict:
    """创建外部正式工单。v1.0 中该协议从未被调用，导致 biz_order_id 恒为 None。"""
    if state.get("biz_order_id"):
        return {}          # 幂等：重放时直接跳过（M4）

    idempotency_key = state.get("idempotency_key") or _derive_idempotency_key(state)
    try:
        result = await deps.order_gateway.create_official_order(
            state["draft"], state["creator_id"], idempotency_key
        )
    except OrderGatewayError:
        # 外部不可用时不得静默继续：显式失败，由上层回退为「转人工」
        raise

    return {
        "biz_order_id": result.biz_order_id,
        "idempotency_key": idempotency_key,
    }
```

#### 节点 2：`safety_review`（**v1.0 缺陷修正：示范代码形同虚设**）

v1.0 的示范代码是：

```python
async def safety_check_node(state):
    violations = []   # 安规校验通过   ← 永远返回"零违规"
    return {"safety_violations": violations}
```

**这是全文最危险的示范代码**：注释写着"安规校验通过"，实际是硬编码恒真。读者照抄即装上一个永远不报警的安全网——比没有安全检查更危险，因为它制造了虚假的安全感。

v2.0 给出真实实现：RAG 检索规程条款 + 强类型结构化判定 + 失败即转人工。

```python
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI


class Violation(BaseModel):
    """单条安规违规。必须携带规程依据，供人工复核。"""

    rule_code: str
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    description: str
    basis_doc: str          # 如《电力安全工作规程 变电部分》第 X 条
    basis_text: str


class SafetyCheckResult(BaseModel):
    risk_level: Literal["LOW", "HIGH", "UNKNOWN"]
    violations: list[Violation] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    reasoning: str


async def safety_review_node(state: WorkflowState, deps: Deps) -> dict:
    """安规判定：检索规程 → 结构化输出 → 强类型校验。

    任何失败路径都不允许返回空违规集；最差情况返回 UNKNOWN 并强制转人工。
    """
    query = _compose_query(state["draft"])

    try:
        chunks = await deps.vector_service.search(query, biz_tag=deps.biz_tag, top_k=RAG_TOP_K)
    except Exception:
        # 检索不可用：保守转人工，绝不"因为查不到就判定合规"
        return {
            "risk_level": "UNKNOWN",
            "violations": [],
            "citations": [],
            "requires_human": True,
        }

    if not chunks:
        return {
            "risk_level": "UNKNOWN",
            "violations": [],
            "citations": [],
            "requires_human": True,
        }

    try:
        llm = ChatOpenAI(
            base_url=deps.settings.llm_base_url,
            api_key=deps.settings.llm_api_key,
            model=deps.settings.llm_model,
            temperature=0.0,          # 合规判定必须确定性（M3）
            timeout=30,
            max_retries=2,
        ).with_structured_output(SafetyCheckResult)

        result: SafetyCheckResult = await llm.ainvoke(
            [
                {"role": "system", "content": SAFETY_SYSTEM_PROMPT},
                {"role": "user", "content": _render_context(query, chunks)},
            ]
        )
    except Exception:
        # 模型超时 / 限流 / 结构校验失败：降级为保守转人工，不阻断流程
        return {
            "risk_level": "UNKNOWN",
            "violations": [],
            "citations": [],
            "requires_human": True,
        }

    # 策略判定（业务规则在插件侧，core 不感知）
    classification = await deps.risk_policy.classify(state["draft"])

    return {
        "risk_level": classification.risk_level,
        "violations": [v.model_dump() for v in result.violations],
        "citations": result.citations,
        "requires_human": classification.requires_human,
    }
```

> **降级链条（必须显式设计，不可省略）**：
> `模型超时/限流` → `UNKNOWN + 转人工` → `策略 classify` → `判定为 HIGH/UNKNOWN` → `必须人工核签`。
> 任何一环失败都不允许落到"自动签发"。

#### 节点 3：`route_by_risk` + `dispatch_to_human`（**v1.0 缺陷修正：闭环断点 2**）

```python
async def route_by_risk_node(state: WorkflowState, deps: Deps) -> str:
    """kill switch：全局关闭自动签发时，一律转人工。"""
    if not deps.settings.autopilot_enabled:
        return "dispatch_to_human"
    return "dispatch_to_human" if state.get("requires_human") else "issue_permit"


async def dispatch_to_human_node(state: WorkflowState, deps: Deps) -> dict:
    """写派单目标。v1.0 中 assigned_role 永远是默认值 APPROVANT，
    导致人审任务永远进不了审批池——人审闭环的第二个断点。"""
    target: DispatchTarget = await deps.dispatch_policy.resolve_target(
        state["draft"], RiskClassification(risk_level=state["risk_level"], requires_human=True, reason="")
    )
    async with deps.session_factory() as session:
        await session.execute(
            text(
                """
                UPDATE ai_thread_mappings
                   SET assigned_role = :role,
                       assigned_scope = :scope,
                       status = 'WAITING_HUMAN',
                       current_node = 'human_gate',
                       updated_at = NOW()
                 WHERE thread_id = :thread_id
                """
            ),
            {"role": target.assigned_role, "scope": target.assigned_scope, "thread_id": state["thread_id"]},
        )
        await session.commit()
    return {"assigned_role": target.assigned_role, "assigned_scope": target.assigned_scope}
```

#### 节点 4：`human_gate`（interrupt 挂起）

```python
from langgraph.types import interrupt


class HumanDecision(BaseModel):
    """人工决策。必须是强类型——interrupt 的恢复值来自外部 HTTP 输入，不可控。"""

    approved: bool
    opinion: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    decided_at: datetime


async def human_gate_node(state: WorkflowState) -> dict:
    """人机协同中断点。

    【铁律 1】本节点必须无副作用。resume 时 LangGraph 会从节点头部重放到
               interrupt() 调用点，副作用会被执行两次。
    【铁律 2】派单写入（assigned_role/scope）必须发生在本节点之前的
               dispatch_to_human，否则重放会重复写。
    """
    decision_payload = interrupt({
        "kind": "dispatch_approval",
        "thread_id": state["thread_id"],
        "biz_order_id": state.get("biz_order_id"),
        "risk_level": state.get("risk_level"),
        "violations": state.get("violations", []),
        "citations": state.get("citations", []),
        "draft": state.get("draft", {}),
    })

    try:
        decision = HumanDecision.model_validate(decision_payload)
    except ValidationError as exc:
        # 恢复值不合法：视为驳回，绝不默认放行
        return {
            "is_permitted": False,
            "audit_opinion": f"人工决策数据不合法，系统按驳回处理：{exc}",
            "reviewer_id": None,
            "final_status": "REJECTED",
        }

    return {
        "is_permitted": decision.approved,
        "audit_opinion": decision.opinion,
        "reviewer_id": decision.reviewer_id,
    }
```

> **v1.0 缺陷修正（两处）**：
> 1. **恢复值未校验**：v1.0 用 `human_decision.get("is_permitted", False)` 假定恢复值是 dict。若前端传 list/字符串会抛 `AttributeError`，且 `get(..., False)` 的默认值语义是"异常时倾向驳回"——但异常本身是崩溃而非驳回。v2.0 用 Pydantic 校验，非法即显式驳回并留痕。
> 2. **未声明重放语义**：v1.0 未说明 `interrupt()` 恢复时节点会重放，读者会把副作用写进 `human_gate`，导致审批意见写两遍、外部单据建两张。v2.0 把这条写成节点级铁律。

#### 节点 5：`issue_permit` / `reject_order`

```python
async def issue_permit_node(state: WorkflowState, deps: Deps) -> dict:
    """签发许可令。fail-closed：biz_order_id 缺失即拒绝签发。"""
    biz_order_id = state.get("biz_order_id")
    if not biz_order_id:
        # v1.0 缺陷修正：v1.0 允许 biz_order_id 为 None 时继续调用，
        # 会用 None 去调用外部签发接口。
        return {
            "is_permitted": False,
            "audit_opinion": "缺少外部工单号，系统拒绝签发许可令",
            "final_status": "REJECTED",
        }

    try:
        permit: OfficialPermit = await deps.credential_gateway.issue_official_permit(
            biz_order_id,
            state["reviewer_id"],
            state["idempotency_key"],
        )
    except Exception as exc:
        # 外部失败不吞异常：交由 finalize 落 FAILED，允许幂等重试
        raise

    return {
        "is_permitted": True,
        "ca_signature_hash": permit.ca_signature_hash,
        "final_status": "PERMITTED",
    }
```

#### 节点 6：`finalize`（**终态唯一写入口，v1.0 缺失**）

```python
async def finalize_node(state: WorkflowState, deps: Deps) -> dict:
    """终态唯一写入口。

    【M5】业务终态只允许由本节点写入。接口层不得直改 ai_thread_mappings.status，
    否则 CAS 抢占、状态机回写、外部系统三者会打架（v1.0 的核心断裂）。
    """
    final_status = state.get("final_status") or ("PERMITTED" if state.get("is_permitted") else "REJECTED")
    async with deps.session_factory() as session:
        await session.execute(
            text(
                """
                UPDATE ai_thread_mappings
                   SET status = :status,
                       audit_opinion = :opinion,
                       signature_hash = :signature,
                       operator_id = :operator,
                       current_node = 'finalize',
                       lock_version = lock_version + 1,
                       updated_at = NOW()
                 WHERE thread_id = :thread_id
                """
            ),
            {
                "status": final_status,
                "opinion": state.get("audit_opinion", ""),
                "signature": state.get("ca_signature_hash"),
                "operator": state.get("reviewer_id"),
                "thread_id": state["thread_id"],
            },
        )
        await session.commit()
    return {"final_status": final_status}
```

### 5.4 状态机装配

```python
# backend/app/plugins/power_grid/graph.py
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def build_graph(checkpointer: AsyncPostgresSaver, deps: Deps):
    """单例编译，无状态计算。checkpointer 在此注入。"""
    builder = StateGraph(WorkflowState)

    builder.add_node("create_official_order", partial(create_official_order_node, deps=deps))
    builder.add_node("safety_review", partial(safety_review_node, deps=deps))
    builder.add_node("dispatch_to_human", partial(dispatch_to_human_node, deps=deps))
    builder.add_node("human_gate", human_gate_node)
    builder.add_node("issue_permit", partial(issue_permit_node, deps=deps))
    builder.add_node("reject_order", partial(reject_order_node, deps=deps))
    builder.add_node("finalize", partial(finalize_node, deps=deps))

    builder.add_edge(START, "create_official_order")
    builder.add_edge("create_official_order", "safety_review")
    builder.add_conditional_edges(
        "safety_review",
        partial(route_by_risk_node, deps=deps),
        {"dispatch_to_human": "dispatch_to_human", "issue_permit": "issue_permit"},
    )
    builder.add_edge("dispatch_to_human", "human_gate")
    builder.add_conditional_edges(
        "human_gate",
        lambda s: "issue_permit" if s.get("is_permitted") else "reject_order",
        {"issue_permit": "issue_permit", "reject_order": "reject_order"},
    )
    builder.add_edge("issue_permit", "finalize")
    builder.add_edge("reject_order", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)
```

### 5.5 HITL 恢复协议（v1.0 完全缺失）

```python
# backend/app/core/workflow/resume.py
from langgraph.types import Command


async def resume_approval(graph, thread_id: str, decision: HumanDecision) -> dict:
    """恢复挂起的人审节点。

    【协议要点】
    1. thread_id 必须来自 ai_thread_mappings，禁止前端自造；
    2. 恢复值必须通过 HumanDecision 强类型校验；
    3. 恢复前必须做归属校验（§8.3），越权直接 403；
    4. 恢复前必须做 CAS 抢占，防止两名审批人同时签核。
    """
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(
        Command(resume=decision.model_dump(mode="json")),
        config=config,
    )
    return result
```

**版本契约**：v1.0 手册未锁 LangGraph 版本，而 `interrupt()` / `Command(resume=)` 的语义在 0.2.x 与后续版本间有演进（`checkpoint_writes` 表结构随版本变化）。v2.0 强制锁定版本矩阵（附录 B），并在 CI 中固定 `langgraph-checkpoint-postgres` 与 `langgraph` 的版本一致性。

---

## 6. 通用 RAG 底座：分块、版本化向量与检索

### 6.1 流式解析（v1.0 缺陷修正：Excel 是伪流式）

v1.0 声称"所有解析器逐行 Yield，全程禁止中途执行 list()"，但 `openpyxl.load_workbook(read_only=True)` **仍会全量载入 sharedStrings 字符串表**——大文件内存照样爆。真正的流式只有 CSV。

```python
# backend/app/core/rag/parsers/base.py
from abc import ABC, abstractmethod
from typing import Iterator

from pydantic import BaseModel


class ParsedDocument(BaseModel):
    title: str
    content: str
    source_path: str
    doc_type: str
    metadata: dict = {}


class BaseParser(ABC):
    @abstractmethod
    def iter_parse(self, file_path: str) -> Iterator[ParsedDocument]:
        """必须逐条产出。调用方严禁 list() 全量物化。"""
```

```python
# backend/app/core/rag/parsers/excel.py
import csv
from typing import Iterator

import openpyxl

from app.core.rag.parsers.base import BaseParser, ParsedDocument
from app.core.rag.chunker import Chunk, Chunker, RecursiveChunker


class ExcelParser(BaseParser):
    """Excel 解析。read_only 避免构建全部单元格对象，
    但 sharedStrings 仍会驻留内存——因此强制按行产出并即时分块入库。"""

    def iter_parse(self, file_path: str) -> Iterator[ParsedDocument]:
        chunker: Chunker = RecursiveChunker()
        if file_path.lower().endswith(".csv"):
            yield from self._iter_csv(file_path, chunker)
        else:
            yield from self._iter_xlsx(file_path, chunker)

    @staticmethod
    def _iter_csv(file_path: str, chunker: Chunker) -> Iterator[ParsedDocument]:
        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as handle:
            reader = csv.reader(handle)
            headers = next(reader, None) or []
            for idx, row in enumerate(reader, start=2):
                content = ", ".join(
                    f"{headers[i]}: {value}"
                    for i, value in enumerate(row)
                    if i < len(headers) and value and value.strip()
                )
                if not content:
                    continue
                for chunk in chunker.split(content):
                    yield ParsedDocument(
                        title=f"行{idx}", content=chunk, source_path=file_path, doc_type="csv"
                    )

    @staticmethod
    def _iter_xlsx(file_path: str, chunker: Chunker) -> Iterator[ParsedDocument]:
        workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        try:
            for sheet in workbook.worksheets:
                rows = sheet.iter_rows(values_only=True)
                headers = [str(h) for h in (next(rows, None) or [])]
                for idx, row in enumerate(rows, start=2):
                    content = ", ".join(
                        f"{headers[i]}: {value}"
                        for i, value in enumerate(row)
                        if i < len(headers) and value is not None
                    )
                    if not content:
                        continue
                    for chunk in chunker.split(content):
                        yield ParsedDocument(
                            title=f"{sheet.title}-行{idx}",
                            content=chunk,
                            source_path=file_path,
                            doc_type="xlsx",
                        )
        finally:
            workbook.close()
```

### 6.2 分块器（v1.0 完全缺失）

```python
# backend/app/core/rag/chunker.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from pydantic import BaseModel

CHUNK_SIZE: int = 512
CHUNK_OVERLAP: int = 64


class Chunk(BaseModel):
    content: str
    index: int
    token_estimate: int


class Chunker(Protocol):
    def split(self, text: str) -> list[Chunk]: ...


class RecursiveChunker:
    """按段落 → 句子 → 字符递归切分，保留重叠窗口。"""

    def __init__(self, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> None:
        if overlap >= size:
            raise ValueError("overlap 必须小于 size")
        self._size = size
        self._overlap = overlap

    def split(self, text: str) -> list[Chunk]:
        segments = _split_by_separator(text, ["\n\n", "\n", "。", "；", ". "])
        chunks: list[Chunk] = []
        buffer = ""
        for segment in segments:
            candidate = f"{buffer}{segment}" if buffer else segment
            if len(candidate) <= self._size:
                buffer = candidate
                continue
            if buffer:
                chunks.append(Chunk(content=buffer, index=len(chunks), token_estimate=len(buffer) // 2))
            if len(segment) > self._size:
                for offset in range(0, len(segment), self._size - self._overlap):
                    piece = segment[offset: offset + self._size]
                    if piece:
                        chunks.append(
                            Chunk(content=piece, index=len(chunks), token_estimate=len(piece) // 2)
                        )
                buffer = ""
            else:
                buffer = segment
        if buffer:
            chunks.append(Chunk(content=buffer, index=len(chunks), token_estimate=len(buffer) // 2))
        return chunks
```

### 6.3 检索（v1.0 缺陷修正：注入旋钮、修正归因）

v1.0 的检索 SQL 有三个问题：
1. **归因错误**：v1.0 红宝书把"召回为 0"归因为归一化问题，并给出 `min_similarity = 0.0` 的兜底——**这等于在规范里教人关闭质量闸门**。真实主因是：HNSW 是近似索引，`WHERE biz_tag=... AND is_active=TRUE AND 相似度>=阈值` 叠加 `ORDER BY 距离 LIMIT k`，近似检索返回的近邻在过滤后可能不足 k 条甚至为空。**正解是 pgvector ≥ 0.8 的迭代扫描**。
2. **参数形态**：v1.0 用 `CAST(:vec_str AS vector)` 传字符串向量，未说明 pgvector 与 asyncpg/SQLAlchemy 的类型适配。
3. **魔法阈值**：`min_sim=0.5` 无来源说明。

```python
# backend/app/core/rag/vector_service.py
from sqlalchemy import text
from pgvector.sqlalchemy import Vector

from app.core.config import Settings
from app.models.ai_schema import AsyncSessionLocal


class VectorService:
    def __init__(self, settings: Settings, embedding_dim: int) -> None:
        self._settings = settings
        self._embedding_dim = embedding_dim

    async def search(
        self,
        query: str,
        biz_tag: str,
        top_k: int = 5,
        min_similarity: float = 0.55,
        embedding_version: str = "v1",
    ) -> list[dict]:
        """向量检索。

        【必须】
        - 开启 hnsw.iterative_scan，否则带过滤条件的 top_k 会召回不足；
        - 按 embedding_version 过滤，杜绝换模型后的新旧向量混存；
        - 相似度阈值来自离线评测集，禁止用 0.0 兜底。
        """
        vector = await self._embed(query)
        stmt = text(
            """
            SELECT doc_code, biz_tag, section_title, content,
                   embedding_model, embedding_version,
                   1 - (embedding <=> CAST(:q AS vector)) AS similarity
              FROM ai_knowledge_base
             WHERE is_active = TRUE
               AND biz_tag = :biz_tag
               AND embedding_version = :embedding_version
               AND 1 - (embedding <=> CAST(:q AS vector)) >= :min_similarity
             ORDER BY embedding <=> CAST(:q AS vector) ASC
             LIMIT :top_k
            """
        ).bindparams(q=Vector(self._embedding_dim))

        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
                await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
                result = await session.execute(
                    stmt,
                    {
                        "q": vector,
                        "biz_tag": biz_tag,
                        "embedding_version": embedding_version,
                        "min_similarity": min_similarity,
                        "top_k": top_k,
                    },
                )
            return [dict(row._mapping) for row in result.fetchall()]
```

**跨业务隔离**：v1.0 用全局单一 HNSW 索引 + `biz_tag` 过滤。近似索引下过滤发生在索引扫描**之后**，理论上可能召回跨业务内容后再过滤。对敏感业务，这意味着"虽然过滤了，但可能召回不足"。规模较大时应按 `biz_tag` **分表建索引**，或使用 pgvector 的分区表 + 分区级 HNSW。

### 6.4 评测（v1.0 完全缺失）

```python
# backend/app/core/rag/evaluation/ — 最小可执行评测集
@dataclass(frozen=True, slots=True)
class EvalCase:
    query: str
    expected_doc_codes: frozenset[str]
    biz_tag: str


# 指标：Recall@k（≥0.9）、引用准确率（≥0.95）、空召回率（=0）
# CI 中以固定种子向量运行，防止真实模型 API 不可用时"检索恒返回 0"被误判为通过
```

> **v1.0 红宝书缺陷修正**：v1.0 建议"本地无真实模型 API 时，单测库改用原语检索（自相似度 1.0）或设置 min_similarity = 0.0"。前者让测试形同虚设（不测真实向量），后者把质量闸门关掉。v2.0 正确做法：**单测用固定种子向量跑离线评测集**，断言 Recall@k 与空召回率，模型不可用时**测试失败**而非静默放宽阈值。

---

## 7. 前端通用工作台与 A2UI 动态卡片

### 7.1 卡片注册表（v1.0 缺陷修正：冲突检测 + 版本化）

```typescript
// frontend/src/core/a2ui/CardRegistry.ts
import { type Component } from 'vue';

export interface CardRegistration {
  component: Component;
  version: string;
}

export class CardRegistry {
  private static registry = new Map<string, CardRegistration>();

  public static register(cardType: string, component: Component, version = 'v1'): void {
    const existing = this.registry.get(cardType);
    if (existing) {
      // v1.0 用 registry.set 直接覆盖，同名卡片后注册者胜出，且依赖 import 顺序。
      // v2.0 显式抛错：卡片类型是跨插件契约，重名必须由人裁决。
      throw new Error(
        `卡片类型 "${cardType}" 已注册（版本 ${existing.version}）。` +
        '卡片类型全局唯一，请改用新的 card_type 或提升版本号。'
      );
    }
    this.registry.set(cardType, { component, version });
  }

  public static get(cardType: string): CardRegistration | undefined {
    return this.registry.get(cardType);
  }
}
```

**插件装配入口（core 只认识 ID，不认识实现）**

```typescript
// frontend/src/core/plugins/registry.ts —— core 内唯一允许出现的插件白名单
export interface PluginDescriptor {
  id: string;
  cards: ReadonlyArray<{ type: string; loader: () => Promise<Component> }>;
  forms: ReadonlyArray<{ type: string; loader: () => Promise<Component> }>;
}

export const PLUGIN_REGISTRY: readonly PluginDescriptor[] = [
  {
    id: 'power_grid',
    cards: [
      { type: 'power_grid.safety_diff', loader: () => import('@/plugins/power_grid/cards/SafetyDiffCard.vue') },
      { type: 'power_grid.permit_result', loader: () => import('@/plugins/power_grid/cards/PermitResultCard.vue') },
    ],
    forms: [
      { type: 'power_grid.substation_apply', loader: () => import('@/plugins/power_grid/forms/SubstationApplyForm.vue') },
    ],
  },
];
```

> **v1.0 缺陷修正**：v1.0 把 `App.vue # 插件装配入口` 直接放在 core 目录树下，等于 core 直接 import 业务插件，隔离公约第一句即破。v2.0 将装配收敛到 `core/plugins/registry.ts`，core 只持有**插件 ID 与懒加载函数**，不认识具体实现；新增插件只改这一个数组。

### 7.2 卡片宿主（v1.0 缺陷修正：去 `any` + 强类型判别联合）

```vue
<!-- frontend/src/core/a2ui/MessageCardHost.vue -->
<template>
  <div class="a2ui-card-container my-3">
    <component
      :is="resolvedComponent"
      v-if="resolvedComponent"
      :key="cardKey"
      :payload="payload"
      @execute-action="onAction"
    />
    <div v-else class="p-3 border border-dashed rounded text-xs text-gray-400">
      ⚠️ 业务插件未注册对应 A2UI 卡片：{{ message.card_type }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { CardRegistry } from './CardRegistry';
import type { ChatMessageRecord, CardActionPayload } from './types';

const props = defineProps<{ message: ChatMessageRecord }>();
const emit = defineEmits<{ (e: 'action', payload: CardActionPayload): void }>();

const resolvedComponent = computed(() =>
  props.message.card_type ? CardRegistry.get(props.message.card_type)?.component : undefined
);

// 按 card_id 复用组件实例：同一张卡片的增量更新不会重挂载、不会重复渲染
const cardKey = computed(() => props.message.card_id ?? props.message.id);

const payload = computed<Record<string, unknown>>(() => props.message.card_payload ?? {});

function onAction(payload: CardActionPayload): void {
  emit('action', payload);
}
</script>
```

> **v1.0 缺陷修正（三处）**：
> 1. **`any` 泄漏**：v1.0 的 `function onAction(payload: any)` 直接违反手册自身的严格 TS 规范。
> 2. **空对象掩盖契约错误**：`card_payload || {}` 会让"后端没下发数据"变成"渲染出一个空表单"，用户提交后才炸。v2.0 用 `?? {}` 且由卡片组件自行对必填字段做运行时校验。
> 3. **卡片重复渲染**：v1.0 以 `:key` 默认的消息 id 渲染，而流式更新每帧一条消息 → 屏幕上出现 N 张重复卡片。v2.0 以 `card_id` 为 key，同一逻辑卡片复用实例。

### 7.3 渲染调度引擎（v1.0 缺陷修正：去炫技、去掉队、背压、可见性降级）

v1.0 的 `RenderTicker` 用 `requestAnimationFrame` 逐字符吐出 token，且**队列无上限**、**后台标签页会卡死**、**字符速率随队列长度动态变化**（视觉上"非匀速喷字"，与真实打字机语义不符）。更根本的是：**把 LLM 流式输出人为延后吐出，纯粹为视觉效果牺牲响应速度**。

v2.0 的原则：**token 直出，不人为延迟**。需要打字机效果时，由 CSS `steps()` 或内容动画实现，不在数据通路上做延迟。

```typescript
// frontend/src/core/engine/render_ticker.ts
export interface TickerOptions {
  /** 每帧最多提交的字符数上限，防止长文本阻塞主线程 */
  charsPerFrame?: number;
  /** 队列容量上限；超出时丢弃最旧的增量并触发 onOverflow */
  maxQueueLength?: number;
}

export class RenderTicker {
  private queue: string[] = [];
  private isTicking = false;
  private readonly charsPerFrame: number;
  private readonly maxQueueLength: number;

  constructor(
    private readonly onConsume: (chunk: string) => void,
    private readonly onOverflow?: () => void,
    options: TickerOptions = {},
  ) {
    this.charsPerFrame = options.charsPerFrame ?? 64;
    this.maxQueueLength = options.maxQueueLength ?? 20000;
  }

  public push(text: string): void {
    if (this.queue.length + text.length > this.maxQueueLength) {
      this.queue.splice(0, this.queue.length + text.length - this.maxQueueLength);
      this.onOverflow?.();
    }
    this.queue.push(text);
    this.schedule();
  }

  private schedule(): void {
    if (this.isTicking) return;
    if (typeof document !== 'undefined' && document.hidden) {
      // 后台标签页：rAF 会被节流至 1fps 甚至暂停。
      // 降级为定时器，保证数据不丢、连接不积压。
      setTimeout(() => this.tick(), 200);
      return;
    }
    this.isTicking = true;
    requestAnimationFrame(() => this.tick());
  }

  private tick(): void {
    this.isTicking = false;
    const count = Math.min(this.charsPerFrame, this.queue.length);
    if (count === 0) return;
    const chunk = this.queue.splice(0, count).join('');
    this.onConsume(chunk);
    this.schedule();
  }
}
```

> **v1.0 缺陷修正**：
> | v1.0 | 后果 | v2.0 |
> |---|---|---|
> | 每帧 2–8 字符 | 1000 字回复需 125–500 帧，人为延迟 | 每帧 64 字符，直出；打字机效果交给 CSS |
> | 队列无上限 | 长回复内存膨胀 + 掉帧 | `maxQueueLength` + 溢出回调 |
> | 无可见性处理 | 后台标签页流式卡死 | `document.hidden` 降级为定时器 |
> | 速率随队列动态变化 | 视觉"忽快忽慢"，语义失真 | 固定速率 |

### 7.4 离线快照与合并（v1.0 缺陷修正：水位比对）

```typescript
// frontend/src/core/engine/storage.ts
export interface SnapshotEnvelope {
  threadId: string;
  /** 服务端快照水位，取自 ai_chat_messages.updated_at 的最大值 */
  watermark: string | null;
  /** 本地生成的卡片草稿，服务端确认后被移除 */
  pendingCards: ReadonlyArray<{ cardId: string; revision: number; payload: Record<string, unknown> }>;
}

export interface MergePolicy {
  /**
   * 服务端为权威源（Convention 1：AI 库是展示快照的唯一权威）。
   * 本地 pendingCards 仅在服务端明确缺少对应 card_id 时保留。
   */
  merge(serverMessages: readonly ChatMessageRecord[], local: SnapshotEnvelope): ChatMessageRecord[];
}
```

**合并规则（必须固化为可测函数，不可散落在组件里）**
1. 服务端 `updated_at` 的最大值作为水位 `watermark`。
2. 本地 `pendingCards` 中，若服务端已存在同 `card_id` 且 `card_revision >=` 本地 revision → 删除本地副本（服务端已确认）。
3. 其余本地卡片保留，并置于服务端消息之后按 `seq` 排序。
4. **不做时间戳比较**（不同设备时钟不可信），只做**服务端版本单调比较**。

> **v1.0 缺陷修正**：v1.0 的 `ai_chat_messages` 无 `updated_at` / `version`，前端 IndexedDB 与服务端快照冲突时**无可比较水位**，只能靠"刷新即渲染"暴力刷新——这是把一致性问题推给用户的降级妥协。v2.0 补齐水位与合并策略。

### 7.5 权限展示

前端权限**只用于展示收敛，不作为安全边界**。真正的拦截在后端（§8.3）。前端按 `principal.roles` 与 `principal.scopes` 决定是否渲染「核签」按钮；隐藏按钮不构成授权，所有授权判定在后端 `authorize_thread` 中完成。

---

## 8. 多角色协同、CAS 乐观锁与运行治理

### 8.1 角色与管辖范围双维度（v1.0 缺陷修正）

v1.0 的派单只有 `assigned_role` 一个维度。电力调度的真实业务是**按调度管辖范围派单**——某变电站的检修工单应派给管辖该变电站的调度值班长，而不是全局所有调度员。v1.0 的模型会让所有调度员互相可见全部工单。

```python
class Principal(BaseModel):
    """请求主体。scopes 为管辖范围标识集合。"""

    user_id: str
    roles: frozenset[str]
    scopes: frozenset[str]
    dept: str
```

### 8.2 审批池路由（v1.0 保留并修正）

```python
# backend/app/api/v1/tasks.py
@router.get("/tasks")
async def list_pending_tasks(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """待办任务审批池：按角色 + 管辖范围双维度过滤。

    v1.0 只按角色过滤，导致所有 DISPATCHER 可见全部工单。
    """
    if "DISPATCHER" not in principal.roles:
        # 提报员身份请求待办池：安全返回空表，不暴露他人工单的存在性。
        return {"total": 0, "items": []}

    stmt = select(AIThreadMapping).where(
        AIThreadMapping.status == "WAITING_HUMAN",
        AIThreadMapping.assigned_role.in_(principal.roles),
        AIThreadMapping.is_archived.is_(False),
    )
    if principal.scopes:
        stmt = stmt.where(
            or_(
                AIThreadMapping.assigned_scope.is_(None),
                AIThreadMapping.assigned_scope.in_(principal.scopes),
            )
        )
    ...
```

### 8.3 归属鉴权（v1.0 完全缺失 → 越权审批面）

v1.0 只在**列表**层做了角色过滤，**审批与签发端点没有任何归属校验**。知道 `thread_id` 即可审批他人工单——这是严重的越权面。

```python
# backend/app/core/acl/authorization.py
from fastapi import HTTPException


async def authorize_thread(session: AsyncSession, principal: Principal, thread_id: str) -> AIThreadMapping:
    """线程级归属校验。列表过滤不能替代端点校验——否则等于无鉴权。"""
    mapping = await session.get(AIThreadMapping, thread_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="工单不存在")

    if mapping.assigned_role not in principal.roles:
        raise HTTPException(status_code=403, detail="该工单未指派给你的角色")

    if mapping.assigned_scope and mapping.assigned_scope not in principal.scopes:
        raise HTTPException(status_code=403, detail="该工单不在你的管辖范围内")

    if mapping.creator_id == principal.user_id and "DISPATCHER" not in principal.roles:
        # 自审自批：除具备独立审批权限外，禁止审批自己发起的工单
        raise HTTPException(status_code=403, detail="禁止审批本人发起的工单")

    return mapping
```

### 8.4 CAS 乐观锁（v1.0 缺陷修正：状态收敛 + 409 语义区分）

v1.0 的 CAS 有三个问题：
1. 写入 `'RUNNING'`，不在状态枚举内，且**没有任何代码把状态写回终态** → 审批一次后任务永久消失、永久不可再审；
2. `409` 同时用于"并发冲突"与"状态非法"，语义混同 → 用户被误导为"被别人抢单"；
3. CAS 只保证数据库行争用，**不保证外部副作用的原子性**。

```python
# backend/app/api/v1/tasks.py
class ApprovalConflict(Exception):
    """CAS 抢占失败。需区分「并发冲突」与「状态非法」。"""


async def claim_for_approval(
    session: AsyncSession,
    thread_id: str,
    principal: Principal,
    expected_version: int,
) -> int:
    """抢占审批权。返回新的 lock_version。

    【原子性说明】CAS 只覆盖数据库内的状态迁移。
    外部副作用（签发许可令）通过幂等键保证可重入，
    因此「CAS 成功但外部调用失败」是可恢复状态，而非数据不一致。
    """
    result = await session.execute(
        text(
            """
            UPDATE ai_thread_mappings
               SET status = 'APPROVING',
                   operator_id = :operator_id,
                   lock_version = lock_version + 1,
                   updated_at = NOW()
             WHERE thread_id = :thread_id
               AND lock_version = :expected_version
               AND status = 'WAITING_HUMAN'
               AND is_archived = FALSE
            RETURNING lock_version
            """
        ),
        {
            "operator_id": principal.user_id,
            "thread_id": thread_id,
            "expected_version": expected_version,
        },
    )
    row = result.first()
    if row is None:
        # 区分两种失败：版本不符（并发冲突）vs 状态不符（已处理/已超时）
        current = await session.get(AIThreadMapping, thread_id)
        if current is None:
            raise HTTPException(status_code=404, detail="工单不存在")
        if current.status != "WAITING_HUMAN":
            raise HTTPException(
                status_code=409,
                detail=f"该工单当前状态为 {current.status}，不可再次审批",
                headers={"X-Conflict-Reason": "STATE_NOT_ACTIONABLE"},
            )
        raise HTTPException(
            status_code=409,
            detail="该工单已被他人处理，请刷新后查看最新状态",
            headers={"X-Conflict-Reason": "VERSION_CONFLICT"},
        )
    await session.commit()
    return int(row[0])
```

**409 语义分离（前端据此给出不同提示）**

| `X-Conflict-Reason` | 含义 | 前端提示 |
|---|---|---|
| `VERSION_CONFLICT` | 另一名审批人已抢占 | "已被他人处理，正在刷新最新状态" |
| `STATE_NOT_ACTIONABLE` | 工单已审批 / 已超时 / 已撤回 | "该工单已不可审批" |

> **v1.0 缺陷修正**：v1.0 统一提示"卡片已被他人处理"。对 `STATE_NOT_ACTIONABLE` 而言这是**误导**——用户会以为被抢单而放弃，实际上工单可能已超时或被撤回。两种情形必须给不同反馈。

### 8.5 超时收敛（v1.0 完全缺失）

```python
# backend/app/core/workflow/reaper.py
async def expire_stale_approvals(session: AsyncSession, ttl_hours: int = 72) -> int:
    """挂起超时的审批任务转 EXPIRED，释放派单占用。

    v1.0 中 WAITING_HUMAN 永不超时，异常中断的工单会永久占用审批池名额。
    """
    result = await session.execute(
        text(
            """
            UPDATE ai_thread_mappings
               SET status = 'EXPIRED',
                   audit_opinion = COALESCE(audit_opinion, '审批超时，系统自动关闭'),
                   current_node = 'expired',
                   lock_version = lock_version + 1,
                   updated_at = NOW()
             WHERE status = 'WAITING_HUMAN'
               AND is_archived = FALSE
               AND expires_at IS NOT NULL
               AND expires_at < NOW()
            """
        )
    )
    await session.commit()
    return result.rowcount
```

### 8.6 运行治理：熔断开关与限流（v1.0 完全缺失）

```python
# backend/app/core/governance.py
class AutopilotGovernor:
    """自动签发总闸。

    AI 判定逻辑出现系统性误判时，必须能一键把全部工单切回人工核签，
    且无需改代码、无需发版（通过环境变量 + 热加载生效）。
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def autopilot_allowed(self) -> bool:
        return self._settings.autopilot_enabled
```

**限流与配额（生产必备，v1.0 缺席）**

| 维度 | 建议初值 | 落点 |
|---|---|---|
| 单用户并发流 | 3 | API 层信号量 |
| 全局并发流 | 200 | API 层信号量 + 连接池反压 |
| 单会话单分钟 token 预算 | 50k | LLM 调用前预检，超限降级 |
| 审批池查询 QPS | 20 / 用户 | 中间件 |

---

## 9. 前后端交互协议（HITL / SSE / A2UI 幂等）

> **本节是 v2.0 的最大增量**。v1.0 把 SSE、A2UI 卡片、人机协同中断三件事分开描述，**从未定义它们如何交互**，导致第 5、7、8 节拼不成一个可运行的系统。本节冻结契约（M6：契约先于实现）。

### 9.1 SSE 事件契约

| 事件类型 | data 结构 | 语义 |
|---|---|---|
| `meta` | `{ thread_id, session_id, message_seq, title }` | 握手帧。必须**第一个**发送，前端据此建立会话 |
| `token` | `{ delta }` | 增量文本。必须直出，不得在服务端缓冲 |
| `card` | `{ card_id, revision, card_type, card_version, payload }` | 卡片首次出现或整体替换 |
| `card_update` | `{ card_id, revision, patch }` | 卡片增量更新。`revision` 必须严格递增 |
| `interrupt` | `{ interrupt_id, kind, payload, expires_at }` | 人工介入请求 |
| `done` | `{ thread_id, status, finish_reason }` | 正常结束。`status` 为终态或 `WAITING_HUMAN` |
| `error` | `{ code, message, retryable }` | 错误。`retryable=false` 时前端不得自动重试 |
| `ping` | `{ ts }` | 心跳保活，间隔 15s |

**协议硬规则**

1. **所有 SSE 帧必须带 `id:` 字段**（自增序号），支持 `Last-Event-ID` 断点续传。
2. **禁止在流内阻塞等待人工**。收到 `interrupt` 后，服务端**必须**：
   - 落库 `ai_chat_messages(kind='interrupt')` + `ai_thread_mappings.status='WAITING_HUMAN'`；
   - 发送 `done` 帧（`status='WAITING_HUMAN'`, `finish_reason='awaiting_human'`）；
   - **关闭本次响应**。
3. **恢复走独立端点**（§9.3），不依赖原长连接存活。前端关闭页面不影响审批任务的存续。
4. **鉴权在请求头**。SSE 端点必须校验 `Authorization`；**禁止把令牌放在 query string**（会进日志、进浏览器历史、进 Referer）。
5. 客户端断连时，服务端必须**取消**上游任务并释放信号量，不得留下悬挂请求。

### 9.2 后端实现骨架

```python
# backend/app/api/v1/agent.py
from fastapi.responses import StreamingResponse


@router.post("/agent/stream")
async def stream_agent(
    payload: ChatRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """SSE 端点。鉴权、限流、信号量、取消传播全部在此收口。"""

    async def event_source() -> AsyncIterator[bytes]:
        event_id = 0
        try:
            async for event in _run_agent_events(payload, principal, session):
                event_id += 1
                yield _sse_frame(event_id, event.type, event.data)
        except asyncio.CancelledError:
            # 客户端断连：取消上游、释放资源，不留悬挂任务
            raise
        except Exception as exc:
            yield _sse_frame(event_id + 1, "error", {"code": "INTERNAL", "message": str(exc), "retryable": False})

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # 关闭 Nginx 缓冲，否则流式被攒包
        },
    )


def _sse_frame(event_id: int, event: str, data: dict) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n".encode("utf-8")
```

### 9.3 人工审批端点（v1.0 完全缺失）

```python
@router.post("/agent/threads/{thread_id}/approval")
async def approve_thread(
    thread_id: str,
    body: ApprovalRequest,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
    graph = Depends(get_agent_graph),
):
    """人审签核。顺序：归属校验 → CAS 抢占 → 恢复状态机。"""
    mapping = await authorize_thread(session, principal, thread_id)

    expected_version = body.lock_version
    if expected_version != mapping.lock_version:
        raise HTTPException(status_code=409, detail="版本冲突，请刷新",
                            headers={"X-Conflict-Reason": "VERSION_CONFLICT"})

    await claim_for_approval(session, thread_id, principal, expected_version)

    decision = HumanDecision(
        approved=body.approved,
        opinion=body.opinion,
        reviewer_id=principal.user_id,
        decided_at=datetime.now(timezone.utc),
    )
    await resume_approval(graph, thread_id, decision)
    return {"thread_id": thread_id}
```

### 9.4 A2UI 卡片幂等协议

**服务端**

```python
async def upsert_card(
    session: AsyncSession,
    thread_id: str,
    card_id: str,
    card_type: str,
    card_version: str,
    payload: dict,
) -> int:
    """按 (thread_id, card_id) 幂等 upsert，返回新的 revision。

    唯一索引 uq_thread_card_rev 保证并发下不产生重复卡片。
    """
    result = await session.execute(
        text(
            """
            INSERT INTO ai_chat_messages
                (id, thread_id, seq, role, kind, card_id, card_revision,
                 card_type, card_version, card_payload, is_sanitized, created_at, updated_at)
            VALUES
                (:id, :thread_id, :seq, 'assistant', 'card', :card_id, 1,
                 :card_type, :card_version, CAST(:payload AS JSONB), TRUE, NOW(), NOW())
            ON CONFLICT (thread_id, card_id, card_revision) DO NOTHING
            RETURNING card_revision
            """
        ),
        {...},
    )
    ...
```

**前端**

```typescript
// frontend/src/core/api/agent.ts（使用 @microsoft/fetch-event-source）
import { fetchEventSource } from '@microsoft/fetch-event-source';

export async function streamAgent(
  body: ChatRequest,
  handlers: StreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  await fetchEventSource('/api/v1/agent/stream', {
    method: 'POST',
    body: JSON.stringify(body),
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${tokenStore.get()}`,
    },
    signal,
    openWhenHidden: true,          // 后台标签页保持连接，避免积压
    onopen: async (response) => {
      if (response.status !== 200) {
        throw new Error(`SSE 连接失败：HTTP ${response.status}`);
      }
      const contentType = response.headers.get('content-type') ?? '';
      if (!contentType.includes('text/event-stream')) {
        throw new Error(`期望 text/event-stream，实际为 ${contentType}`);
      }
    },
    onmessage: (event) => {
      switch (event.event) {
        case 'token':
          handlers.onToken(JSON.parse(event.data).delta);
          break;
        case 'card':
          handlers.onCard(JSON.parse(event.data));
          break;
        case 'card_update':
          handlers.onCardUpdate(JSON.parse(event.data));
          break;
        case 'interrupt':
          handlers.onInterrupt(JSON.parse(event.data));
          break;
        case 'done':
          handlers.onDone(JSON.parse(event.data));
          break;
        case 'error': {
          const payload = JSON.parse(event.data) as { code: string; message: string; retryable: boolean };
          handlers.onError(payload);
          if (!payload.retryable) throw new Error(payload.message);
          break;
        }
        default:
          break;
      }
    },
    onerror: (error) => {
      handlers.onError({ code: 'STREAM_ERROR', message: String(error), retryable: true });
    },
  });
}
```

> **v1.0 缺陷修正（协议缺失清单）**：
> | v1.0 | 后果 | v2.0 |
> |---|---|---|
> | 无 SSE 事件类型定义 | 前后端各自实现，无法联调 | §9.1 冻结 8 类事件 + 帧结构 |
> | 中断时流阻塞等待人工 | 客户端一关页面，审批请求永久悬挂 | §9.1 硬规则 2：立即落库 + 关流 |
> | 卡片无幂等键 | 流式更新渲染出 N 张重复卡片 | §9.4 按 `(thread_id, card_id)` upsert |
> | 卡片无版本 | 历史快照用新渲染器回放崩溃 | `card_version` + 注册表版本映射 |
> | 无断点续传 | 断网后整段重来 | 帧带 `id:`，支持 `Last-Event-ID` |

---

## 10. 可观测性与成本治理

### 10.1 Trace 埋点（v1.0 死表修正）

v1.0 定义了 `ai_execution_traces` 表的全部字段，却在全文**没有任何一处写入**——手册宣称"Token 成本可控"，实际零落地。

```python
# backend/app/core/observability/trace.py
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import perf_counter

from langchain_core.outputs import LLMResult


@dataclass(slots=True)
class TraceRecord:
    thread_id: str
    node_name: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: Decimal = Decimal("0")
    latency_ms: int = 0
    error_log: str | None = None
    tool_calls: dict | None = None
    extra: dict = field(default_factory=dict)


@asynccontextmanager
async def trace_call(session_factory, record: TraceRecord):
    """LLM 调用埋点。异常路径也必须落库——失败调用的成本同样要计费。"""
    started = perf_counter()
    try:
        yield record
    except Exception as exc:
        record.error_log = f"{type(exc).__name__}: {exc}"
        record.latency_ms = int((perf_counter() - started) * 1000)
        await _persist(session_factory, record)
        raise
    else:
        record.latency_ms = int((perf_counter() - started) * 1000)
        await _persist(session_factory, record)
```

```python
def _apply_usage(record: TraceRecord, result: LLMResult) -> None:
    usage = result.llm_output or {}
    token_usage = usage.get("token_usage") or {}
    record.prompt_tokens = int(token_usage.get("prompt_tokens", 0))
    record.completion_tokens = int(token_usage.get("completion_tokens", 0))
    record.total_cost = Decimal(str(usage.get("total_cost", 0)))
```

### 10.2 消息序号原子分配

```python
async def allocate_seq(session: AsyncSession, thread_id: str) -> int:
    """会话内单调序号。使用行级原子自增，避免并发插入顺序不确定。"""
    result = await session.execute(
        text(
            """
            UPDATE ai_thread_mappings
               SET next_seq = next_seq + 1
             WHERE thread_id = :thread_id
            RETURNING next_seq
            """
        ),
        {"thread_id": thread_id},
    )
    row = result.first()
    if row is None:
        raise LookupError(f"未知 thread_id: {thread_id}")
    return int(row[0])
```

### 10.3 对话正文脱敏（v1.0 漏洞修正）

公约 1 声明"严禁双写业务主数据"，但 `ai_chat_messages.content` 是自由文本，用户粘贴的工单号、身份证号会被静默落库。v1.0 的 `is_sanitized` 只是一个**没有任何执行者的标记位**。

```python
# backend/app/core/security/sanitizer.py
import re

_PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b\d{17}[\dXx]\b"), "[身份证号]"),
    (re.compile(r"\b1[3-9]\d{9}\b"), "[手机号]"),
    (re.compile(r"\b\d{19}\b"), "[银行卡号]"),
    (re.compile(r"(?<=OMS-)\d{8}-\w{6}"), "[工单号]"),
)


def sanitize(text: str) -> tuple[str, bool]:
    """返回 (脱敏后文本, 是否发生脱敏)。规则化脱敏，不依赖模型自查。"""
    changed = False
    for pattern, placeholder in _PII_PATTERNS:
        text, count = pattern.subn(placeholder, text)
        if count:
            changed = True
    return text, changed
```

**落库前必须调用**：`content, sanitized = sanitize(raw)`，然后 `is_sanitized = sanitized or <内容由系统生成>`。禁止由模型自行声称已脱敏。

### 10.4 关键指标（生产必备，v1.0 缺席）

| 指标 | 采集点 | 告警阈值 |
|---|---|---|
| 端到端首字延迟 P95 | SSE `meta` → 首个 `token` | > 3s |
| 安规判定 UNKNOWN 率 | `safety_review` 返回值 | > 5%（疑似模型/检索劣化） |
| 审批平均停留时长 | `WAITING_HUMAN` 时长分布 | > 24h |
| CAS 冲突率 | 409 计数 | > 2% |
| 外部网关失败率 | ACL 异常计数 | > 1% |
| 单会话 token 消耗 | trace 汇总 | 超预算告警 |

---

## 11. 部署、迁移、灰度与回滚

### 11.1 启动自检（v1.0 完全缺失）

```python
# backend/app/core/bootstrap.py
async def startup_self_check(engine) -> None:
    """启动期阻断式自检。任何一项失败都必须阻断启动，而不是带着隐患运行。"""
    settings = get_settings()

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        row = (await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))).first()
        if row is None:
            raise RuntimeError("pgvector 扩展不可用")
        version = str(row[0])
        if tuple(int(p) for p in version.split(".")[:2]) < (0, 8):
            # 迭代扫描需 pgvector >= 0.8，否则带过滤条件的 top_k 会召回不足
            raise RuntimeError(f"pgvector 版本过低（{version}），需 >= 0.8 以支持 hnsw.iterative_scan")

    # 连接预算
    row = (await conn.execute(text("SHOW max_connections"))).first()
    if row and int(row[0]) < 80:
        raise RuntimeError(f"max_connections={row[0]} 低于规划下限 80，请扩容或下调池大小")

    # 凭据完备性（生产）
    if settings.is_production:
        if not settings.enterprise_order_gateway_url:
            raise RuntimeError("生产环境缺少工单网关配置，拒绝启动")
```

### 11.2 迁移 SOP

1. 所有 DDL 走 Alembic，脚本**双向可回滚**。
2. 破坏性变更四步走：`加列 → 双写 → 切读 → 删列`（跨版本发布）。
3. HNSW 索引使用 `CREATE INDEX CONCURRENTLY`（`op.get_context().autocommit_block()`），禁止在业务时段建索引。
4. 迁移前自动备份：`pg_dump --format=custom`（归档到对象存储，保留 30 天）。
5. 大表 `ALTER TABLE` 必须设置 `lock_timeout = '3s'`，超时即失败回滚——避免迁移把业务库锁死。

### 11.3 灰度与回滚（v1.0 完全缺失）

| 阶段 | 范围 | 准入条件 | 回滚条件 |
|---|---|---|---|
| 影子 | 新旧双写，不对外 | 迁移脚本演练通过 | 任一 P0 缺陷 |
| 5% | 按用户 ID 哈希分流 | 影子期 P95 延迟无劣化 | 审批成功率下降 > 1pt |
| 50% | 扩大分流 | UNKNOWN 率 < 5% | 外部网关失败率 > 1% |
| 100% | 全量 | 连续 72h 无 P0/P1 | —— |

**回滚预案（必须写进发布单）**
- 数据库：迁移为可逆脚本，`alembic downgrade` 即可。
- 应用：保留上一版本镜像，5 分钟内可切回。
- 业务态：已签发的许可令**不可回滚**（已发到现场）。因此灰度期必须**强制低风险自动签发关闭**（`AI_AUTOPILOT_ENABLED=false`），只验证人审链路；自动签发能力在链路稳定后再单独开灰度。

### 11.4 部署形态

```text
前端：静态资源 → CDN / Nginx
后端：uvicorn --workers N --loop asyncio（Windows 单进程；Linux 多进程）
      Nginx 反代需关闭 SSE 缓冲：proxy_buffering off; proxy_read_timeout 3600s;
      X-Accel-Buffering: no
数据库：PostgreSQL 16 + pgvector ≥ 0.8，独立实例或独立 schema，不与业务主库共用
```

> **SSE 反代是高频事故点**：Nginx 默认会缓冲上游响应，导致流式变成"一次性吐出"。必须在反代层关闭 `proxy_buffering`，并在应用层加 `X-Accel-Buffering: no` 头。

---

## 12. 测试策略

### 12.1 测试金字塔

| 层级 | 范围 | 工具 | 门禁 |
|---|---|---|---|
| 单元 | 分块器、状态转换、CAS SQL、脱敏规则 | pytest | 覆盖率 ≥ 80% |
| 契约 | ACL 适配器响应校验、SSE 事件结构、卡片 upsert | pytest + httpx MockTransport | 零破坏性变更 |
| 集成 | 状态机全链路（含 interrupt/resume） | pytest + 真实 Postgres（容器） | 全绿 |
| 端到端 | 提报 → 审批 → 签发 | Playwright | 核心路径每日跑 |
| 混沌 | 网关超时、DB 抖动、模型限流 | 故障注入 | 关键降级路径必过 |

### 12.2 必测的边界用例（每条对应一个真实缺陷）

| 用例 | 断言 |
|---|---|
| `POST /agent/stream` 无令牌 | 401，且响应体不含令牌回显 |
| 审批端点传他人 `thread_id` | 403 |
| 审批端点传过期 `lock_version` | 409 + `X-Conflict-Reason: VERSION_CONFLICT` |
| 审批已过期工单 | 409 + `X-Conflict-Reason: STATE_NOT_ACTIONABLE` |
| 两次并发审批同一工单 | 恰好一个 200、一个 409 |
| 审批后查询工单 | `status` 为 `PERMITTED`/`REJECTED`（**不是** `APPROVING`/`RUNNING`） |
| `interrupt` 后关闭浏览器 | 工单仍在审批池中可见 |
| 同一 `card_id` 连续 3 帧更新 | 数据库 1 行；前端 1 个组件实例 |
| `safety_review` 检索失败 | `risk_level=UNKNOWN` 且 `requires_human=True`（**绝不返回空违规集**） |
| LLM 返回非法结构 | 降级转人工，不崩溃 |
| 生产环境缺网关配置 | **启动失败**（不是静默 Mock） |
| `Vector` 维度不匹配的向量入库 | 被拒绝（不静默截断） |

### 12.3 隔离性静态检查

```python
# backend/scripts/check_plugin_isolation.py
"""插件隔离静态检查。CI 门禁，违反即失败。

v1.0 的隔离是「约定性」的——靠人读代码遵守。本脚本把它变成「强制性」的。
"""
FORBIDDEN_IN_CORE = [
    "power_grid", "voltage", "substation", "调度", "安规", "检修", "工作票",
]
ALLOWED_CORE_IMPORTS = {
    "app.core", "app.services.acl", "langgraph", "langchain_core",
    "pydantic", "sqlalchemy", "fastapi",
}


def check_core_purity(core_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in core_dir.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for keyword in FORBIDDEN_IN_CORE:
            if keyword in source:
                violations.append(f"{path}: core 中出现业务专有标识 '{keyword}'")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0:2]
                joined = ".".join(root)
                if not any(joined.startswith(a) for a in ALLOWED_CORE_IMPORTS):
                    violations.append(f"{path}: core 非法依赖 {node.module}")
    return violations
```

> **v1.0 缺陷修正**：v1.0 的 `check_plugin_isolation.py` 未说明其检出能力与盲区，隔离实质上是**约定性**的。v2.0 用 AST 静态检查把"core 不得出现业务标识、不得反向依赖业务包"变成 CI 门禁。

---

## 13. 新业务插件接入 SOP

### 13.1 六步法

| 步骤 | 产出 | 校验点 |
|---|---|---|
| **1. 定义业务契约** | `schemas.py`（强类型入参/出参）、`policy.py`（风险分级 + 派单策略） | 契约不得包含 `dict` 自由结构 |
| **2. 实现状态机** | `graph.py`：在 `core/workflow/base_graph.py` 的抽象上实现节点 | 节点不得直接写 `ai_thread_mappings`（终态由 `finalize` 统一写） |
| **3. 实现防渗透适配** | `adapters/xxx_adapter.py`，实现 core ACL 的 Protocol | 外部响应必须 Pydantic 强类型；失败必须抛 |
| **4. 实现 A2UI 卡片** | 前端 `plugins/<biz>/cards/*.vue`，`CardRegistry.register` | 卡片类型全局唯一；必须声明 `card_version` |
| **5. 注册装配** | 后端 `core/plugin/manifest.py` + 前端 `core/plugins/registry.ts` 各加一行 | **core 零改动** |
| **6. 打通测试与文档** | §12.2 边界用例 + 业务 SOP 文档 | CI 全绿 + 隔离检查通过 |

### 13.2 接入检查清单

- [ ] 风险分级策略实现在插件侧，core 未新增任何业务常量
- [ ] 外部副作用全部带幂等键
- [ ] 中断节点无副作用，恢复值经 Pydantic 校验
- [ ] 终态由 `finalize` 统一写回，接口层无直改 status 的代码
- [ ] 审批端点调用了 `authorize_thread`
- [ ] SSE 中断后已落库并关流
- [ ] 卡片按 `(thread_id, card_id)` 幂等 upsert
- [ ] `is_sanitized` 由脱敏器真实置位
- [ ] `AIExecutionTrace` 有埋点
- [ ] `.env.example` 已补充新增环境变量
- [ ] `alembic revision` 脚本可升可降

---

## 14. 避坑红宝书（v2 修订版）

| 现象 | 真实原因 | 正确处理 | v1.0 原条目状态 |
|---|---|---|---|
| SSE 通了但内容一次性吐出 | Nginx 缓冲 | `proxy_buffering off` + `X-Accel-Buffering: no` | **新增** |
| SSE 连上后一直转圈 | 服务端在流内阻塞等人审 | 中断即落库并关流，恢复走独立端点 | **新增（v1.0 缺失协议）** |
| 单测向量召回恒为 0 | pgvector 版本过低未开迭代扫描；或用真实模型 API 不可用时静默放宽阈值 | 升 pgvector ≥ 0.8 并开 `hnsw.iterative_scan`；单测用固定种子向量跑离线评测集，**禁止 `min_similarity = 0.0`** | **修正**（v1.0 归因为归一化，且建议 0.0 兜底） |
| 审批一次后工单消失 | 状态写 `'RUNNING'` 且无终态回写 | 统一 7 态，终态由 `finalize` 唯一写入口 | **修正**（v1.0 缺陷） |
| 审批按钮 409 一直失败 | `lock_version` 为 NULL（原生 SQL 插入） | 补 `server_default`，并对存量数据回填 | **修正**（v1.0 缺失） |
| 卡片重复渲染 N 张 | 卡片缺幂等键 | 按 `(thread_id, card_id)` upsert，前端以 `card_id` 为 key | **修正**（v1.0 缺失） |
| 历史卡片回放崩溃 | 卡片契约无版本 | `card_version` + 注册表版本映射 | **修正**（v1.0 缺失） |
| 审批后意见/签名丢失 | 字段无落库路径 | `finalize` 统一落 `audit_opinion` / `signature_hash` | **修正**（v1.0 缺失） |
| 生产发出不存在的工单号 | 网关 URL 缺失时静默回落 Mock | prod 缺配置即启动失败；Mock 仅 dev 可达 | **修正**（v1.0 缺陷） |
| 时间戳差 8 小时 | `datetime.utcnow` + 无时区列 | `DateTime(timezone=True)` + `datetime.now(timezone.utc)` | **修正**（v1.0 缺陷） |
| Excel 导入内存爆 | `read_only` 仍全量载入 sharedStrings | 逐行产出 + 即时分块入库 | **修正**（v1.0 伪流式） |
| 换了嵌入模型检索变差 | 新旧向量静默混存 | `embedding_version` 隔离 + 双写灰度切换 | **修正**（v1.0 缺失） |
| 后台标签页流式卡死 | rAF 被节流 | `document.hidden` 时降级为定时器 | **修正**（v1.0 缺失） |
| 提报员请求待办池 403 | 端点一律拒绝 | 安全返回空表 `{total:0, items:[]}` | 保留（v1.0 正确） |
| 审批池出现别人的工单 | 只按角色过滤，无管辖范围 | 补 `assigned_scope` 双维度过滤 | **修正**（v1.0 缺失） |
| 自审自批 | 无创建人校验 | `authorize_thread` 禁止本人审批 | **新增** |
| 审批任务永久占位 | 无超时 | `expires_at` + reaper 转 `EXPIRED` | **新增** |
| AI 误判批量签发 | 无总闸 | `AI_AUTOPILOT_ENABLED=false` 一键转人工 | **新增** |
| Vite 代理 502 | `localhost` 解析为 IPv6 `::1`，Uvicorn 只监听 IPv4 | target 写 `http://127.0.0.1:8000`；或 Uvicorn 加 `--host 0.0.0.0` | 保留 |
| API 401 | 读写令牌 key 不一致 | 统一 `TOKEN_STORAGE_KEY`；登录时用登录端点换取真实 JWT | 保留 |
| PowerShell 多行脚本卡在 `>>` | 续行符在语法错误分支 | 严禁粘贴多行；用独立 `.py` 脚本 | 保留 |

---

## 附录 A 审计 → 修订对照表

| # | 审计发现（v1.0） | 严重度 | v2.0 修订位置 |
|---|---|---|---|
| 1 | 生产库凭据明文硬编码 | P0 | §3.1 `config.py` + `.env.example`，缺失即启动失败 |
| 2 | `AsyncConnectionPool` 无 `open()`/`close()` | P0 | §3.2 生命周期 + FastAPI `lifespan` |
| 3 | 缺 checkpointer 建表与 `CREATE EXTENSION vector` | P0 | §3.4 `ensure_database_ready` |
| 4 | `safety_check_node` 恒返回空违规集 | P0 | §5.3 节点 2：RAG + 结构化输出 + 失败转人工 |
| 5 | 网关缺失时静默回落 Mock | P0 | §4.2 失败即抛；prod 启动自检 |
| 6 | 外部响应裸 `dict` 索引 | P1 | §4.1/§4.2 Pydantic 强类型 + 枚举校验 |
| 7 | `verify_token` 为同步签名 | P1 | §4.3 改 `async def` |
| 8 | `biz_order_id` 无来源，闭环断裂 | P0 | §5.3 节点 1 `create_official_order` |
| 9 | `assigned_role` 无写入路径 | P0 | §5.3 节点 3 `dispatch_to_human` |
| 10 | 状态枚举与 CAS 写入不一致、终态不回写 | P0 | §3.3 七态 + §5.3 节点 6 `finalize` |
| 11 | `audit_opinion`/`signature_hash`/`current_node` 无落库 | P0 | §5.3 节点 6 |
| 12 | 审批端点无归属校验（越权） | P0 | §8.3 `authorize_thread` |
| 13 | 派单只有角色维度 | P1 | §3.3 `assigned_scope` + §8.2 双维度过滤 |
| 14 | HITL 中断与 SSE 交互未定义 | P0 | §9.1 事件契约 + 硬规则 2 |
| 15 | 卡片无幂等键 / 无版本 | P0 | §3.3 卡片四列 + §9.4 upsert |
| 16 | 消息无序号、无水位 | P1 | §3.3 `seq` + §10.2 原子分配 + §7.4 合并 |
| 17 | 风险分级硬编码在核心 | P1 | §5.2 策略 SPI，插件实现 |
| 18 | 双连接池因果表述错误 | P2 | §1.1 公约 2 三条真实收益 |
| 19 | 事件循环策略理由缺失、作用域失控 | P1 | §3.2 独立模块 + 真实理由 + 弃用风险 |
| 20 | `min_similarity` 归因错误、建议 0.0 兜底 | P1 | §6.3 迭代扫描 + §14 红宝书修正 |
| 21 | xlsx 伪流式 | P1 | §6.1 + §14 |
| 22 | RAG 缺 chunker / rerank / eval | P1 | §6.2 / §6.4 |
| 23 | embedding 维度硬编码、换模型静默混存 | P1 | §3.3 版本三元组 + §6.3 换模型 SOP |
| 24 | `AIExecutionTrace` 死表 | P1 | §10.1 埋点 |
| 25 | `Numeric` 标注为 `float` | P2 | §3.3 改 `Decimal` |
| 26 | `datetime.utcnow` naive | P1 | §3.3 `utcnow()` + 时区列 |
| 27 | `lock_version` 缺 `server_default` | P1 | §3.3 |
| 28 | 409 语义混同 | P1 | §8.4 `X-Conflict-Reason` |
| 29 | CAS 与外部副作用非原子 | P1 | §5.3 幂等键 + §8.4 原子性说明 |
| 30 | `interrupt()` 重放语义未声明 | P1 | §5.3 节点 4 铁律 1/2 |
| 31 | 恢复值未强类型校验 | P1 | §5.3 节点 4 `HumanDecision` |
| 32 | `App.vue` 在 core 内破坏隔离 | P1 | §7.1 `core/plugins/registry.ts` 白名单 |
| 33 | `services/acl/` 分类灰区 | P2 | §2.2 切分 core/acl 与 plugins/adapters |
| 34 | `is_sanitized` 无执行者 | P1 | §10.3 规则化脱敏器 |
| 35 | 无迁移方案、无版本矩阵 | P1 | §3.4 + 附录 B |
| 36 | 无灰度/回滚/kill switch | P1 | §8.6 + §11.3 |
| 37 | 无超时收敛 | P1 | §8.5 reaper |
| 38 | 零测试策略 | P1 | §12 |
| 39 | 隔离检查形同虚设 | P1 | §12.3 AST 门禁 |
| 40 | 渲染引擎队列无上限、后台卡死 | P2 | §7.3 背压 + 可见性降级 |
| 41 | `CardRegistry` 同名静默覆盖 | P2 | §7.1 显式抛错 |
| 42 | `onAction(payload: any)` 违反严格 TS | P2 | §7.2 `CardActionPayload` |
| 43 | `card_payload \|\| {}` 掩盖契约错误 | P2 | §7.2 `?? {}` + 组件内必填校验 |
| 44 | 无启动自检、无连接预算 | P1 | §3.2 预算表 + §11.1 |
| 45 | 幂等键错位（放在会话行而非副作用） | P1 | §3.3 + §5.3 幂等键透传 |
| 46 | 无自审自批防护 | P1 | §8.3 |

---

## 附录 B 版本矩阵与环境变量清单

### B.1 依赖版本矩阵（必须锁定，升级需走灰度）

| 组件 | 版本 | 理由 |
|---|---|---|
| Python | 3.11 – 3.13 | 3.14+ 事件循环策略 API 弃用，需先改造 §3.2 |
| fastapi | 0.115.x | 稳定版 |
| uvicorn[standard] | 0.32.x | — |
| pydantic | 2.9.x | v2 校验语义 |
| langgraph | 0.2.x | `interrupt()` / `Command(resume=)` 语义；须与下一行同版本验证 |
| langgraph-checkpoint-postgres | 0.2.x | **必须与 langgraph 同版本**，表结构随版本演进 |
| sqlalchemy[asyncio] | 2.0.x | — |
| asyncpg | 0.29.x | Windows 需 Selector 事件循环 |
| psycopg[binary,pool] | 3.2.x | 池默认关闭态，需显式 `open()` |
| pgvector | ≥ 0.8 | **0.8 起支持 `hnsw.iterative_scan`** |
| PostgreSQL | 16.x | — |
| openpyxl | 3.1.x | — |
| Node.js | 18+ | — |
| @microsoft/fetch-event-source | 2.0.1 | 前端 SSE 客户端 |

### B.2 环境变量清单

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `APP_ENV` | 否 | `dev` | `dev`/`staging`/`prod`；prod 触发 fail-fast 校验 |
| `PG_ASYNC_URI` | **是** | — | SQLAlchemy asyncpg 连接串 |
| `PG_PSYCOPG_URI` | **是** | — | psycopg 连接串（checkpointer） |
| `PG_POOL_SIZE` | 否 | `20` | 业务池基础容量 |
| `PG_MAX_OVERFLOW` | 否 | `10` | 业务池溢出 |
| `CHECKPOINTER_POOL_SIZE` | 否 | `20` | 检查点池容量 |
| `ENTERPRISE_ORDER_GATEWAY_URL` | prod **是** | — | 工单网关；prod 缺失则启动失败 |
| `ENTERPRISE_IAM_GATEWAY_URL` | prod **是** | — | 身份网关 |
| `IAM_JWT_SECRET` | **是** | — | JWT 验签密钥（独立于模型密钥） |
| `LLM_BASE_URL` | **是** | — | 模型服务地址 |
| `LLM_API_KEY` | **是** | — | 模型服务密钥 |
| `LLM_MODEL` | 否 | `gpt-4o-mini` | 合规判定节点强制 temperature=0 |
| `EMBEDDING_MODEL` | 否 | `text-embedding-v3` | 嵌入模型标识 |
| `EMBEDDING_DIM` | 否 | `1536` | 必须与模型实际维度一致 |
| `EMBEDDING_VERSION` | 否 | `v1` | 向量版本；换模型走灰度 |
| `AI_AUTOPILOT_ENABLED` | 否 | `true` | **kill switch**：关闭后全部转人工 |
| `APPROVAL_TTL_HOURS` | 否 | `72` | 审批超时回收时长 |
| `RAG_TOP_K` | 否 | `5` | 检索条数 |
| `RAG_MIN_SIMILARITY` | 否 | `0.55` | 阈值，须来自离线评测集 |
| `SSE_HEARTBEAT_SECONDS` | 否 | `15` | SSE 心跳间隔 |
| `RATE_LIMIT_PER_USER` | 否 | `20` | 待办池 QPS 上限 |

---

## 结语

v2.0 与 v1.0 的差别不在篇幅，而在**三件事**：

1. **所有"看起来在做事"的代码都真的在做**——安全节点不再恒返回空违规集，Trace 表真的有埋点，终态真的有写入口。
2. **所有跨系统边界都强类型化、失败即抛**——外部脏数据在防腐层被拦截，生产漏配绝不静默降级。
3. **所有跨进程交互都有冻结的契约**——SSE 事件、中断恢复、卡片幂等、消息序号，全部先定义再实现。

这三件事是"A 级"与"B 级"的分界线：前者可以交给一个团队照着施工并验收，后者只能作为讨论蓝图的起点。
