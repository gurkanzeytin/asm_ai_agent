import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.services.interfaces import IWorkflowService

logger = logging.getLogger(__name__)


class GenerateReportNode(IAgentNode):
    """Workflow node responsible for generating analytical narrative reports from query execution results."""

    def __init__(self, workflow_service: IWorkflowService):
        self.workflow_service = workflow_service

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateReportNode execution started.")
        start_time = time.perf_counter()

        # If errors already present, skip execution defensively
        if state.errors:
            logger.warning("GenerateReportNode skipped: errors are present on incoming state.")
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "current_node": "generate_report",
                    "duration_ms": state.duration_ms + duration,
                }
            )

        if not state.query_result:
            logger.error("GenerateReportNode failed: query_result is missing in state.")
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "errors": state.errors + ["GenerateReportNode failed: SQL query result is missing."],
                    "current_node": "generate_report",
                    "duration_ms": state.duration_ms + duration,
                }
            )

        if not state.generated_sql or not state.generated_sql.sql:
            logger.error("GenerateReportNode failed: generated_sql is missing in state.")
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "errors": state.errors + ["GenerateReportNode failed: Generated SQL statement is missing."],
                    "current_node": "generate_report",
                    "duration_ms": state.duration_ms + duration,
                }
            )

        try:
            report_dto = await self.workflow_service.execute_report_generation(
                question=state.question,
                sql=state.generated_sql.sql,
                query_result=state.query_result,
                execution_id=state.workflow_id,
            )

            logger.info("GenerateReportNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "generated_report": report_dto,
                    "current_node": "generate_report",
                    "completed_nodes": state.completed_nodes + ["generate_report"],
                    "duration_ms": state.duration_ms + duration,
                }
            )
        except Exception as e:
            logger.error(f"GenerateReportNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"GenerateReportNode failed: {e}"],
                    "current_node": "generate_report",
                    "duration_ms": state.duration_ms + duration,
                }
            )
