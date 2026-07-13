import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.insights.insight_engine import InsightEngine

logger = logging.getLogger(__name__)


class GenerateInsightsNode(IAgentNode):
    """Workflow node running the Insight Intelligence Engine after analytics.

    Enrichment layer: skipped when no analytics is available, and any failure is
    logged and swallowed so report generation always continues. The LLM (when
    available) only verbalizes deterministic analytics — it never calculates.
    """

    def __init__(self, insight_engine: InsightEngine | None = None):
        self.insight_engine = insight_engine or InsightEngine()

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateInsightsNode execution started.")
        start_time = time.perf_counter()

        if state.errors or state.analytics is None:
            logger.warning(
                "GenerateInsightsNode skipped: no analytics result on incoming state."
            )
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "current_node": "generate_insights",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_insights": duration},
                }
            )

        try:
            insight_result = await self.insight_engine.generate(state.analytics)

            logger.info("GenerateInsightsNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "insights": insight_result,
                    "current_node": "generate_insights",
                    "completed_nodes": state.completed_nodes + ["generate_insights"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_insights": duration},
                }
            )
        except Exception as e:
            # Deliberately non-fatal: insights must never block report generation.
            logger.error(f"GenerateInsightsNode execution failed (non-fatal): {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "current_node": "generate_insights",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_insights": duration},
                }
            )
