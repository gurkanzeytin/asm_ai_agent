import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.analytics.result_validation import ResultValidator
from app.application_models.outcome import AgentOutcome
from app.services.interfaces import IWorkflowService

logger = logging.getLogger(__name__)

# Database errors worth one SQL regeneration attempt: the SQL itself is wrong
# in a way the LLM can plausibly fix when shown the error (AG-022).
_RETRYABLE_ERROR_MARKERS = (
    # SQL Server (T-SQL)
    "invalid column name",
    "invalid object name",
    "ambiguous column name",
    "incorrect syntax near",
    "is invalid in the select list because it is not contained in either "
    "an aggregate function or the group by clause",
    "order by items must appear in the select list",
    "multi-part identifier",
)

# Errors that must never trigger an SQL rewrite: authentication, authorization,
# network, timeout, or server availability problems are not fixable by the LLM.
_NON_RETRYABLE_ERROR_MARKERS = (
    "login failed",
    "login timeout",
    "permission was denied",
    "permission denied",
    "the server was not found",
    "server is not found or not accessible",
    "network-related",
    "communication link failure",
    "connection is broken",
    "connection refused",
    "connection reset",
    "timeout expired",
    "query timeout",
    "ssl provider",
    "certificate verify",
    "not currently available",
)


def _retryable_error(error_text: str) -> bool:
    lowered = error_text.lower()
    if any(marker in lowered for marker in _NON_RETRYABLE_ERROR_MARKERS):
        return False
    return any(marker in lowered for marker in _RETRYABLE_ERROR_MARKERS)


ADAPTIVE_EMPTY_RESULT_PREFIX = "ADAPTIVE_EMPTY_RESULT"


class ExecuteSQLNode(IAgentNode):
    """Workflow node responsible for executing safety-validated SQL queries."""

    def __init__(self, workflow_service: IWorkflowService):
        self.workflow_service = workflow_service
        self._result_validator = ResultValidator()

    def _adaptive_feedback(self, state: AgentState, query_result) -> str | None:
        """Builds widening guidance when an empty result deserves one requery."""
        if query_result.row_count > 0 or state.sql_retry_count > 0:
            return None
        plan = state.query_plan
        if plan is None:
            return None
        hints: list[str] = []
        if plan.date_filters:
            hints.append(
                "The date range may be too narrow; widen it (e.g. extend to the "
                "last 90 days) while keeping the same grouping."
            )
        if any("RandevuDurumu" in extra for extra in plan.extra_filters):
            hints.append(
                "The status literal may not match stored values; verify it against "
                "the verified RandevuDurumu values (Beklemede, Gelmedi, Gerçekleşti, "
                "Giriş Yapılmış, İşlem Sürmekte) or drop the status filter "
                "and group by RandevuDurumu instead. There is no 'İptal' status."
            )
        if plan.cohort:
            hints.append(
                "The cohort window may be too strict; relax it moderately "
                "(e.g. 48 hours instead of 24) and label the relaxation."
            )
        if not hints:
            return None
        return (
            f"{ADAPTIVE_EMPTY_RESULT_PREFIX}: the query executed but returned 0 rows. "
            + " ".join(hints)
        )

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

            # AI-INTELLIGENCE-008 adaptive fallback: an empty result on a plan
            # that carries narrowing constraints (date range, status literal,
            # cohort) earns ONE adaptive requery with widening guidance. Reuses
            # the AG-022 rewrite loop, so the retry budget stays shared at 1.
            adaptive_feedback = self._adaptive_feedback(state, query_result)
            if adaptive_feedback is not None:
                duration = (time.perf_counter() - start_time) * 1000
                logger.warning(
                    "ExecuteSQLNode: empty result on a constrained plan; "
                    "scheduling one adaptive requery."
                )
                return state.model_copy(
                    update={
                        "last_execution_error": adaptive_feedback,
                        "sql_retry_count": 1,
                        "current_node": "execute_sql",
                        "duration_ms": state.duration_ms + duration,
                        "node_timings": {**state.node_timings, "execute_sql": duration},
                    }
                )

            logger.info("ExecuteSQLNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            expected_aliases = state.generated_sql.expected_aliases if state.generated_sql else []
            metric_aliases = state.generated_sql.metric_aliases if state.generated_sql else {}
            shape_verdict = self._result_validator.check_shape(
                query_result, state.query_plan, expected_aliases
            )
            # Safe diagnostic trace of the plan->SQL->result data contract —
            # ids/column names/counts only, never row values or PII, so a
            # multi-metric coverage gap can be traced without a live DB.
            logger.info(
                "ExecuteSQLNode data-contract trace.",
                extra={
                    "planned_metric_ids": (
                        state.query_plan.metrics if state.query_plan else []
                    ),
                    "planned_metric_aliases": metric_aliases,
                    "planned_dimension_ids": (
                        state.query_plan.dimensions if state.query_plan else []
                    ),
                    "expected_aliases": expected_aliases,
                    "result_columns": query_result.columns,
                    "result_row_count": query_result.row_count,
                    "result_first_row_keys": (
                        sorted(query_result.rows[0].keys()) if query_result.rows else []
                    ),
                    "result_shape_valid": shape_verdict.valid,
                    "result_shape_reason": shape_verdict.reason,
                },
            )
            if not shape_verdict.valid:
                logger.warning(
                    "ExecuteSQLNode: result shape verdict invalid: %s",
                    shape_verdict.reason,
                    extra={
                        "missing_columns": shape_verdict.missing_columns,
                        "unexpected_columns": shape_verdict.unexpected_columns,
                    },
                )

            return state.model_copy(
                update={
                    "query_result": query_result,
                    "result_shape_verdict": shape_verdict,
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
