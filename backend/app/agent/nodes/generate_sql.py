import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.services.interfaces import IWorkflowService

logger = logging.getLogger(__name__)


class GenerateSQLNode(IAgentNode):
    """Workflow node responsible for invoking LLM SQL generation services.

    Depends only on IWorkflowService. Prompt rendering is performed exactly once
    inside WorkflowService.execute_sql_generation(); the rendered prompt is returned
    on GeneratedSQL.rendered_prompt and stored in state for observability.
    """

    def __init__(self, workflow_service: IWorkflowService):
        self.workflow_service = workflow_service

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateSQLNode execution started.")
        start_time = time.perf_counter()

        try:
            # SQL generation must see the query-analysis normalized question so domain
            # synonyms (e.g. "kalp" -> "kardiyoloji") reach the SQL prompt.
            question = state.question
            if state.database_context and state.database_context.normalized_query:
                question = state.database_context.normalized_query
                if question != state.question:
                    logger.info(
                        "GenerateSQLNode using normalized question.",
                        extra={
                            "original_question": state.question,
                            "normalized_question": question,
                        },
                    )

            # Prompt is rendered once inside WorkflowService and attached to the DTO
            generated_sql = await self.workflow_service.execute_sql_generation(
                question, database_context=state.database_context
            )

            logger.info("GenerateSQLNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    # Preserve rendered prompt in state for tracing/observability
                    "sql_prompt": generated_sql.rendered_prompt,
                    "generated_sql": generated_sql,
                    "current_node": "generate_sql",
                    "completed_nodes": state.completed_nodes + ["generate_sql"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_sql": duration},
                }
            )
        except Exception as e:
            logger.error(f"GenerateSQLNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"GenerateSQLNode failed: {e}"],
                    "current_node": "generate_sql",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_sql": duration},
                }
            )
