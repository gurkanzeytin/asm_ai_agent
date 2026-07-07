from typing import Any

from app.agent.graph import AgentGraphBuilder
from app.agent.state import AgentState


class LazyAgentGraph:
    """Lazy proxy wrapper around the compiled state graph.

    Defers loading of the AppContainer until the graph is first invoked.
    This resolves import-time circular dependencies between the bootstrap container
    and agent node definition modules.
    """

    def __init__(self):
        self._graph = None

    def _get_graph(self) -> Any:
        if self._graph is None:
            from app.bootstrap import container

            self._graph = container.agent_graph
        return self._graph

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        return await self._get_graph().ainvoke(*args, **kwargs)

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_graph().invoke(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_graph(), name)


agent_graph = LazyAgentGraph()

__all__ = [
    "AgentState",
    "AgentGraphBuilder",
    "agent_graph",
]
