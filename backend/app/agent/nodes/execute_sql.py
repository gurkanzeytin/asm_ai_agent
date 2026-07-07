import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.services.interfaces import IWorkflowService

logger = logging.getLogger(__name__)


class ExecuteSQLNode(IAgentNode):
    """Workflow node responsible for executing safety-validated SQL queries."""

    def __init__(self, workflow_service: IWorkflowService):
        self.workflow_service = workflow_service

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("ExecuteSQLNode execution started.")
        start_time = time.perf_counter()

        # If errors already present, skip execution defensively
        if state.errors:
            logger.warning("ExecuteSQLNode skipped: errors are present on incoming state.")
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "current_node": "execute_sql",
                    "duration_ms": state.duration_ms + duration,
                }
            )

        if not state.generated_sql or not state.generated_sql.sql:
            logger.error("ExecuteSQLNode failed: generated_sql is missing in state.")
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "errors": state.errors + ["ExecuteSQLNode failed: Generated SQL statement is missing."],
                    "current_node": "execute_sql",
                    "duration_ms": state.duration_ms + duration,
                }
            )

        try:
            sql = state.generated_sql.sql
            query_result = await self.workflow_service.execute_query(sql)

            logger.info("ExecuteSQLNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "query_result": query_result,
                    "current_node": "execute_sql",
                    "completed_nodes": state.completed_nodes + ["execute_sql"],
                    "duration_ms": state.duration_ms + duration,
                }
            )
        except Exception as e:
            logger.error(f"ExecuteSQLNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"ExecuteSQLNode failed: {e}"],
                    "current_node": "execute_sql",
                    "duration_ms": state.duration_ms + duration,
                }
            )
