import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.analytics.analytics_engine import AnalyticsEngine

logger = logging.getLogger(__name__)


class AnalyzeResultsNode(IAgentNode):
    """Workflow node running the deterministic Analytics Engine after SQL execution.

    Analytics is an enrichment layer: any failure here is logged and swallowed so
    the report pipeline always continues. No LLM calls are made in this node.
    """

    def __init__(self, analytics_engine: AnalyticsEngine | None = None):
        self.analytics_engine = analytics_engine or AnalyticsEngine()

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("AnalyzeResultsNode execution started.")
        start_time = time.perf_counter()

        # Pass through untouched when upstream failed or produced no result.
        if state.errors or not state.query_result or not state.query_result.success:
            logger.warning(
                "AnalyzeResultsNode skipped: no successful query result on incoming state."
            )
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "current_node": "analyze_results",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "analyze_results": duration},
                }
            )

        try:
            # Analyze against the NLU-normalized question when available so
            # analytical wording matches the same canonical vocabulary as SQL.
            question = state.question
            if state.database_context and state.database_context.normalized_query:
                question = state.database_context.normalized_query

            analytics_result = self.analytics_engine.analyze(question, state.query_result)

            logger.info("AnalyzeResultsNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "analytics": analytics_result,
                    "current_node": "analyze_results",
                    "completed_nodes": state.completed_nodes + ["analyze_results"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "analyze_results": duration},
                }
            )
        except Exception as e:
            # Deliberately non-fatal: analytics must never block report generation.
            logger.error(f"AnalyzeResultsNode execution failed (non-fatal): {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "current_node": "analyze_results",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "analyze_results": duration},
                }
            )
