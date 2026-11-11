"""通用工作流底座（跨业务可复用）。

对外暴露：
- BaseWorkflowState：通用运行态基类
- GraphRegistry：工作流图注册中心（依赖反转）
- HITLController：CAS 并发 / 待办 / 终态
- MessageRecorder：卡片 / 消息持久化
- ThreadMappingStore：线程映射建档 / 归档
"""

from app.core.workflow.base_state import BaseWorkflowState
from app.core.workflow.graph_registry import (
    DEFAULT_GRAPH_NAME,
    GraphRegistry,
)
from app.core.workflow.hitl import HITLController
from app.core.workflow.message_recorder import MessageRecorder
from app.core.workflow.thread_mapping_store import ThreadMappingStore

__all__ = [
    "BaseWorkflowState",
    "GraphRegistry",
    "DEFAULT_GRAPH_NAME",
    "HITLController",
    "MessageRecorder",
    "ThreadMappingStore",
]