"""工作流图注册中心（依赖反转）。

通用底座不直接 import 任何垂直业务图；由各业务插件在装配阶段
（应用 lifespan 或测试 bootstrap）将已编译图注册到本中心，
HITL 控制器据此取得“当前工作流图”。
"""

from typing import Any

# 默认注册名：单图业务直接注册到此槽位
DEFAULT_GRAPH_NAME = "DEFAULT"


class GraphRegistry:
    """已编译工作流图的进程内注册表。"""

    _graphs: dict[str, Any] = {}

    @classmethod
    def register_graph(cls, name: str, graph: Any) -> None:
        """注册（或覆盖）指定名称的已编译工作流图。"""
        cls._graphs[name] = graph

    @classmethod
    def get_graph(cls, name: str = DEFAULT_GRAPH_NAME) -> Any:
        """按名称取图；未注册时抛出明确的架构级异常（不暴露隐晦 KeyError）。"""
        graph = cls._graphs.get(name)
        if graph is None:
            raise RuntimeError(
                "未找到已注册的工作流图，请确认是否已执行 register_graph"
                f"（请求 name={name}）。"
            )
        return graph

    @classmethod
    def clear(cls) -> None:
        """清空注册表（主要用于测试隔离）。"""
        cls._graphs.clear()