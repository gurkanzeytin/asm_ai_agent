import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.services.interfaces import IPromptService

logger = logging.getLogger(__name__)


class RetrieveContextNode(IAgentNode):
    """Workflow node responsible for discovering relevant database schema metadata context."""

    def __init__(self, prompt_service: IPromptService):
        self.prompt_service = prompt_service

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("RetrieveContextNode execution started.")
        start_time = time.perf_counter()

        try:
            db_context = await self.prompt_service.retrieve_schema_context(state.question)
            logger.info("RetrieveContextNode completed successfully.")

            duration = (time.perf_counter() - start_time) * 1000

            # Return copied immutable Pydantic state
            return state.model_copy(
                update={
                    "database_context": db_context,
                    "current_node": "retrieve_context",
                    "completed_nodes": state.completed_nodes + ["retrieve_context"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "retrieve_context": duration},
                }
            )

        except Exception as e:
            logger.error(f"RetrieveContextNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"RetrieveContextNode failed: {e}"],
                    "current_node": "retrieve_context",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "retrieve_context": duration},
                }
            )

