import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome

logger = logging.getLogger(__name__)


class GenerateSchemaCapabilityNode(IAgentNode):
    """Wraps a catalog-derived schema answer without SQL, DB, or LLM access."""

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateSchemaCapabilityNode execution started.")
        start_time = time.perf_counter()
        capability = state.schema_capability_answer
        markdown = capability.markdown if capability else (
            "Bu kolon için doğrulanmış bir yetenek açıklaması bulunamadı."
        )
        report = GeneratedReport(
            title=capability.business_name if capability else "Kolon Yeteneği",
            markdown=markdown,
            provider="static",
            model="schema_capability_service",
            latency_ms=0.0,
        )
        duration = (time.perf_counter() - start_time) * 1000
        return state.model_copy(
            update={
                "generated_report": report,
                "outcome": AgentOutcome.RETURN_HELP.value,
                "response_mode": "answer",
                "current_node": "generate_schema_capability",
                "completed_nodes": state.completed_nodes + ["generate_schema_capability"],
                "duration_ms": state.duration_ms + duration,
                "node_timings": {
                    **state.node_timings,
                    "generate_schema_capability": duration,
                },
            }
        )
