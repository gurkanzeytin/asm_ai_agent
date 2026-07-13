import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.intelligence.observation_engine import ObservationEngine

logger = logging.getLogger(__name__)


class GenerateObservationsNode(IAgentNode):
    """Workflow node running the Observation Engine after insight generation.

    Enrichment layer: skipped without analytics, and any failure is logged and
    swallowed so report generation always continues.
    """

    def __init__(self, observation_engine: ObservationEngine | None = None):
        self.observation_engine = observation_engine or ObservationEngine()

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateObservationsNode execution started.")
        start_time = time.perf_counter()

        if state.errors or state.analytics is None:
            logger.warning(
                "GenerateObservationsNode skipped: no analytics result on incoming state."
            )
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "current_node": "generate_observations",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_observations": duration},
                }
            )

        try:
            observation_result = await self.observation_engine.generate(
                state.analytics, state.insights
            )

            logger.info("GenerateObservationsNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "observations": observation_result,
                    "current_node": "generate_observations",
                    "completed_nodes": state.completed_nodes + ["generate_observations"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_observations": duration},
                }
            )
        except Exception as e:
            # Deliberately non-fatal: observations must never block the pipeline.
            logger.error(f"GenerateObservationsNode execution failed (non-fatal): {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "current_node": "generate_observations",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_observations": duration},
                }
            )
