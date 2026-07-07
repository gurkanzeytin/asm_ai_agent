import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.services.interfaces import IPromptService, IWorkflowService

logger = logging.getLogger(__name__)


class GenerateSQLNode(IAgentNode):
    """Workflow node responsible for invoking LLM SQL generation services."""

    def __init__(self, prompt_service: IPromptService, workflow_service: IWorkflowService):
        self.prompt_service = prompt_service
        self.workflow_service = workflow_service

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateSQLNode execution started.")
        start_time = time.perf_counter()

        try:
            # Render and cache the prompt text for tracing/transparency
            sql_prompt = await self.prompt_service.render_sql_prompt(state.question)

            # Delegate text generation orchestration to application services
            generated_sql = await self.workflow_service.execute_sql_generation(state.question)

            logger.info("GenerateSQLNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "sql_prompt": sql_prompt,
                    "generated_sql": generated_sql,
                    "current_node": "generate_sql",
                    "completed_nodes": state.completed_nodes + ["generate_sql"],
                    "duration_ms": state.duration_ms + duration,
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
                }
            )
