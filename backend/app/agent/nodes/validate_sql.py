import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


class ValidateSQLNode(IAgentNode):
    """Workflow node responsible for verifying SQL query safety metadata."""

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("ValidateSQLNode execution started.")
        start_time = time.perf_counter()

        duration = (time.perf_counter() - start_time) * 1000

        if not state.generated_sql:
            logger.error("ValidateSQLNode failed: GeneratedSQL missing in state.")
            return state.model_copy(
                update={
                    "errors": state.errors + ["ValidateSQLNode failed: Generated SQL is missing."],
                    "current_node": "validate_sql",
                    "duration_ms": state.duration_ms + duration,
                }
            )

        validation_result = state.generated_sql.validation_result
        if not validation_result or not validation_result.valid:
            reason = validation_result.reason if validation_result else "No validation metadata present."
            logger.warning(f"SQL validation safety block triggered. Reason: {reason}")
            return state.model_copy(
                update={
                    "errors": state.errors + [f"SQL Safety validation failed: {reason}"],
                    "current_node": "validate_sql",
                    "duration_ms": state.duration_ms + duration,
                }
            )

        logger.info("ValidateSQLNode execution completed successfully.")
        return state.model_copy(
            update={
                "current_node": "validate_sql",
                "completed_nodes": state.completed_nodes + ["validate_sql"],
                "duration_ms": state.duration_ms + duration,
            }
        )
