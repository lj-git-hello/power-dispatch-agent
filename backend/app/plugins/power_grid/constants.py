"""电网业务插件常量（插件私有）。

集中承载插件名、图注册名、路由前缀与卡片类型，避免魔法值散落。
单独成模块的原因：plugin.py 需导入 router.py，router.py 需引用图注册名，
两者互相 import 会形成循环依赖；constants.py 作为双方共同的下游可彻底避开。
"""

# 插件唯一名（须与插件目录名一致）
POWER_PLUGIN_NAME = "power_grid"
# 插件语义化版本（前后端版本偏斜检测用）
POWER_PLUGIN_VERSION = "1.0.0"
# 状态机在 GraphRegistry 中的注册名（必须显式传名，避免唤醒错图）
POWER_GRAPH_NAME = "power_grid"
# 路由挂载前缀（含 /api）
POWER_ROUTER_PREFIX = "/api/v1/power-dispatch"

# ---- 卡片类型（对齐后端实际下发的 wire 协议） ----
POWER_CARD_TYPE_DISPATCHER_AUDIT = "dispatcher_audit"
POWER_CARD_TYPE_PERMIT_RESULT = "permit_result"
# 对话问答的规程引文卡（经通用对话网关下发）
POWER_CARD_TYPE_CITATIONS = "power_grid_citations"

# ---- 角色 / 状态 ----
POWER_ROLE_DISPATCHER = "DISPATCHER"
POWER_ROLE_APPLICANT = "APPLICANT"
POWER_STATUS_WAITING_HUMAN = "WAITING_HUMAN"
POWER_STATUS_PERMITTED = "PERMITTED"
POWER_STATUS_REJECTED = "REJECTED"
# 安规校验未通过：流程在提报阶段即终止，不进入人工审批队列
POWER_STATUS_SAFETY_REJECTED = "SAFETY_REJECTED"

# ---- 端点路径（相对 POWER_ROUTER_PREFIX） ----
POWER_ENDPOINT_TASKS = "/tasks"
POWER_ENDPOINT_MESSAGES = "/messages"
POWER_ENDPOINT_RESUME = "/audit"
POWER_ENDPOINT_APPLY = "/apply"

# ---- 知识库检索 ----
# 向量库 biz_tag（安规规程切片入库时写入的标签）
POWER_RAG_BIZ_TAG = "power_grid"

__all__ = [
    "POWER_PLUGIN_NAME",
    "POWER_PLUGIN_VERSION",
    "POWER_GRAPH_NAME",
    "POWER_ROUTER_PREFIX",
    "POWER_CARD_TYPE_DISPATCHER_AUDIT",
    "POWER_CARD_TYPE_PERMIT_RESULT",
    "POWER_CARD_TYPE_CITATIONS",
    "POWER_ROLE_DISPATCHER",
    "POWER_ROLE_APPLICANT",
    "POWER_STATUS_WAITING_HUMAN",
    "POWER_STATUS_PERMITTED",
    "POWER_STATUS_REJECTED",
    "POWER_STATUS_SAFETY_REJECTED",
    "POWER_ENDPOINT_TASKS",
    "POWER_ENDPOINT_MESSAGES",
    "POWER_ENDPOINT_RESUME",
    "POWER_ENDPOINT_APPLY",
    "POWER_RAG_BIZ_TAG",
]
