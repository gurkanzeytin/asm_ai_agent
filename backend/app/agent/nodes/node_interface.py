from abc import ABC, abstractmethod

from app.agent.state import AgentState


class IAgentNode(ABC):
    """Base interface representing single responsibility workflow nodes."""

    @abstractmethod
    async def execute(self, state: AgentState) -> AgentState:
        """Executes operations on incoming state and returns copied/updated AgentState.

        Args:
            state: The active workflow state.

        Returns:
            AgentState: The copied state with execution updates.
        """
        pass
