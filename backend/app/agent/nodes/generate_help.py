import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.services.interfaces import IHelpService

logger = logging.getLogger(__name__)


class GenerateHelpNode(IAgentNode):
    """Workflow node responsible for rendering helper documentation query answers.

    Uses HelpService to dynamically retrieve help text without contacting external LLMs.
    """

    def __init__(self, help_service: IHelpService):
        """Initializes the node with help service.

        Args:
            help_service: Configured IHelpService instance.
        """
        self.help_service = help_service

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateHelpNode execution started.")
        start_time = time.perf_counter()

        try:
            help_markdown = self.help_service.get_help_markdown()

            report_dto = GeneratedReport(
                title="Help Guidance",
                markdown=help_markdown,
                provider="static",
                model="help_service",
                latency_ms=0.0,
            )

            logger.info("GenerateHelpNode completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "generated_report": report_dto,
                    "outcome": AgentOutcome.RETURN_HELP.value,
                    "current_node": "generate_help",
                    "completed_nodes": state.completed_nodes + ["generate_help"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_help": duration},
                }
            )

        except Exception as e:
            logger.error(f"GenerateHelpNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"GenerateHelpNode failed: {e}"],
                    "current_node": "generate_help",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_help": duration},
                }
            )
