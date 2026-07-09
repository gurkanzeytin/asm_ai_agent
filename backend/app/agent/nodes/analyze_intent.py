import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.services.interfaces import IIntentClassifier

logger = logging.getLogger(__name__)


class AnalyzeIntentNode(IAgentNode):
    """Workflow node responsible for classifying the intent of the incoming user question."""

    def __init__(self, intent_classifier: IIntentClassifier):
        """Initializes the node with an intent classifier.

        Args:
            intent_classifier: Configured IIntentClassifier instance.
        """
        self.intent_classifier = intent_classifier

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("AnalyzeIntentNode execution started.")
        start_time = time.perf_counter()

        try:
            intent_result = self.intent_classifier.classify(state.question)

            duration = (time.perf_counter() - start_time) * 1000
            logger.info("AnalyzeIntentNode completed successfully.")

            return state.model_copy(
                update={
                    "intent": intent_result,
                    "current_node": "analyze_intent",
                    "completed_nodes": state.completed_nodes + ["analyze_intent"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "analyze_intent": duration},
                }
            )

        except Exception as e:
            logger.error(f"AnalyzeIntentNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"AnalyzeIntentNode failed: {e}"],
                    "current_node": "analyze_intent",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "analyze_intent": duration},
                }
            )
