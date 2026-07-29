import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome

logger = logging.getLogger(__name__)


class GenerateConversationMemoryNode(IAgentNode):
    """Emits a deterministic answer to a meta-question ABOUT the conversation.

    The answer text is precomputed from the retained ConversationContext in
    ReportingService (via ContextManager.conversation_memory_answer) and carried
    on `state.conversation_memory_answer`. This node only wraps it in a
    GeneratedReport — no LLM, no SQL, no database access.
    """

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateConversationMemoryNode execution started.")
        start_time = time.perf_counter()

        markdown = state.conversation_memory_answer or (
            "Bu sohbette henüz kaydedilmiş bir soru geçmişi yok."
        )
        report_dto = GeneratedReport(
            title="Sohbet Hafızası",
            markdown=markdown,
            provider="static",
            model="conversation_memory_node",
            latency_ms=0.0,
        )

        duration = (time.perf_counter() - start_time) * 1000
        logger.info("GenerateConversationMemoryNode completed.")
        return state.model_copy(
            update={
                "generated_report": report_dto,
                "outcome": AgentOutcome.RETURN_HELP.value,
                "response_mode": "answer",
                "current_node": "generate_conversation_memory",
                "completed_nodes": state.completed_nodes + ["generate_conversation_memory"],
                "duration_ms": state.duration_ms + duration,
                "node_timings": {**state.node_timings, "generate_conversation_memory": duration},
            }
        )
