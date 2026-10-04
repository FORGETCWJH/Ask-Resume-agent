"""一个用户动作对应一张短图：执行节点后立即结束，不在图内等待输入。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # 本地未安装可选依赖时保留确定性 MVP 回退
    END = START = StateGraph = None


class AgentGraphState(TypedDict, total=False):
    result: Any


async def run_short_graph(handler: Callable[[], Awaitable[Any]], node_name: str = "execute") -> Any:
    if StateGraph is None:
        return await handler()

    async def execute(_state: AgentGraphState) -> AgentGraphState:
        return {"result": await handler()}

    graph = StateGraph(AgentGraphState)
    graph.add_node(node_name, execute)
    graph.add_edge(START, node_name)
    graph.add_edge(node_name, END)
    compiled = graph.compile()
    output = await compiled.ainvoke({})
    return output["result"]
