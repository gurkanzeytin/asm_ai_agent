import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.services.interfaces import IIntentClassifier
from app.services.query_analyzer import QueryAnalyzer

logger = logging.getLogger(__name__)


class AnalyzeIntentNode(IAgentNode):
    """Workflow node responsible for classifying the intent of the incoming user question."""

    def __init__(
        self,
        intent_classifier: IIntentClassifier,
        query_analyzer: QueryAnalyzer | None = None,
    ):
        """Initializes the node with an intent classifier.

        Args:
            intent_classifier: Configured IIntentClassifier instance.
            query_analyzer: Optional analyzer used for ambiguity detection.
        """
        self.intent_classifier = intent_classifier
        self.query_analyzer = query_analyzer or QueryAnalyzer()

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("AnalyzeIntentNode execution started.")
        start_time = time.perf_counter()

        try:
            intent_result = self.intent_classifier.classify(state.question)
            ambiguity = self.query_analyzer.detect_ambiguity(state.question)
            if ambiguity:
                logger.info(
                    "Ambiguous ranking phrase detected; clarification will be requested.",
                    extra={
                        "question": state.question,
                        "matched_phrase": ambiguity.matched_phrase,
                    },
                )

            duration = (time.perf_counter() - start_time) * 1000
            logger.info("AnalyzeIntentNode completed successfully.")

            return state.model_copy(
                update={
                    "intent": intent_result,
                    "ambiguity": ambiguity,
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
