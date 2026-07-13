import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport

logger = logging.getLogger(__name__)


class GenerateClarificationNode(IAgentNode):
    """Workflow node responsible for asking the user to clarify their request when intent is UNKNOWN."""

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateClarificationNode execution started.")
        start_time = time.perf_counter()

        try:
            if state.ambiguity is not None:
                option_lines = "\n".join(f"• {option}" for option in state.ambiguity.options)
                clarification_text = f"{state.ambiguity.question}\n\n{option_lines}".strip()
                title = "Netleştirme Gerekli"
            else:
                clarification_text = (
                    "I'm not sure what you'd like to know. Could you rephrase your question?"
                )
                title = "Clarification Required"

            report_dto = GeneratedReport(
                title=title,
                markdown=clarification_text,
                provider="static",
                model="clarification_node",
                latency_ms=0.0,
            )

            logger.info("GenerateClarificationNode completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "generated_report": report_dto,
                    "current_node": "generate_clarification",
                    "completed_nodes": state.completed_nodes + ["generate_clarification"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_clarification": duration},
                }
            )

        except Exception as e:
            logger.error(f"GenerateClarificationNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"GenerateClarificationNode failed: {e}"],
                    "current_node": "generate_clarification",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_clarification": duration},
                }
            )
