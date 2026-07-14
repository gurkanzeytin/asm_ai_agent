import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.outcome import AgentOutcome
from app.services.interfaces import IWorkflowService

logger = logging.getLogger(__name__)

# Database errors worth one SQL regeneration attempt: the SQL itself is wrong
# in a way the LLM can plausibly fix when shown the error (AG-022).
_RETRYABLE_ERROR_MARKERS = (
    "no such column",
    "no such table",
    "syntax error",
    "ambiguous column",
    "misuse of aggregate",
    "no such function",
)


def _retryable_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return any(marker in lowered for marker in _RETRYABLE_ERROR_MARKERS)


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
                    "node_timings": {**state.node_timings, "execute_sql": duration},
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
                    "node_timings": {**state.node_timings, "execute_sql": duration},
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
                    # A success after the rewrite loop resolves as REWRITE_AND_RETRY
                    "outcome": (
                        AgentOutcome.REWRITE_AND_RETRY.value
                        if state.sql_retry_count > 0
                        else state.outcome
                    ),
                    "last_execution_error": None,
                    "current_node": "execute_sql",
                    "completed_nodes": state.completed_nodes + ["execute_sql"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "execute_sql": duration},
                }
            )
        except Exception as e:
            duration = (time.perf_counter() - start_time) * 1000
            error_text = str(e)

            # AG-022: one rewrite-and-retry for SQL-shaped database errors.
            # Marked via last_execution_error WITHOUT appending to state.errors,
            # so the retry loop (execute_sql -> generate_sql) stays open.
            if state.sql_retry_count == 0 and _retryable_error(error_text):
                logger.warning(
                    f"ExecuteSQLNode failed with retryable database error; "
                    f"scheduling one SQL rewrite: {error_text}"
                )
                return state.model_copy(
                    update={
                        "last_execution_error": error_text,
                        "sql_retry_count": 1,
                        "current_node": "execute_sql",
                        "duration_ms": state.duration_ms + duration,
                        "node_timings": {**state.node_timings, "execute_sql": duration},
                    }
                )

            logger.error(f"ExecuteSQLNode execution failed: {e}")
            return state.model_copy(
                update={
                    "errors": state.errors + [f"ExecuteSQLNode failed: {e}"],
                    "current_node": "execute_sql",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "execute_sql": duration},
                }
            )
