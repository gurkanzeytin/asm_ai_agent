import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.context.analytical_signals import merge_query_plans
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.services.interfaces import IPromptService
from app.services.query_analyzer import QueryAnalyzer

logger = logging.getLogger(__name__)


class RetrieveContextNode(IAgentNode):
    """Workflow node responsible for discovering relevant database schema metadata context."""

    def __init__(
        self,
        prompt_service: IPromptService,
        query_analyzer: QueryAnalyzer | None = None,
        query_planner: QueryPlanner | None = None,
    ):
        self.prompt_service = prompt_service
        self.query_analyzer = query_analyzer or QueryAnalyzer()
        self.query_planner = query_planner or QueryPlanner()

    def _build_plan(self, question: str, db_context, semantic_frame=None) -> QueryPlan | None:
        """Builds the deterministic query plan (AG-022). Degrades to None on failure."""
        try:
            analysis = self.query_analyzer.analyze(question)
            return self.query_planner.build_plan(
                question,
                analysis,
                db_context.tables,
                semantic_frame=semantic_frame,
                views=db_context.views,
            )
        except Exception as error:
            logger.error(f"Query planning failed; continuing without a plan: {error}")
            return None

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("RetrieveContextNode execution started.")
        start_time = time.perf_counter()

        try:
            db_context = await self.prompt_service.retrieve_schema_context(state.question)
            planning_question = state.raw_question or state.question
            planning_frame = None if state.context_follow_up_detected else state.semantic_frame
            query_plan = self._build_plan(planning_question, db_context, planning_frame)
            if query_plan is not None:
                query_plan = merge_query_plans(
                    current=query_plan,
                    retained=state.retained_query_plan,
                    raw_question=planning_question,
                    follow_up_detected=state.context_follow_up_detected,
                )

            # AG-022: the schema context must contain every table the plan
            # requires (fact table, join hops) or the schema-identifier guard
            # would reject correctly planned SQL. Re-plan after extending so
            # the FK join path can traverse the added tables.
            if query_plan is not None:
                required = {query_plan.fact_table, query_plan.output_table}
                required.update(step.from_table for step in query_plan.join_path)
                required.update(step.to_table for step in query_plan.join_path)
                required.discard(None)
                existing = {table.name for table in db_context.tables}
                existing.update(view.name for view in db_context.views)
                missing = sorted(required - existing)
                extend = getattr(self.prompt_service, "extend_context_with_tables", None)
                if missing and extend is not None:
                    db_context = await extend(db_context, missing)
                    query_plan = (
                        merge_query_plans(
                            current=(
                                self._build_plan(planning_question, db_context, planning_frame)
                                or query_plan
                            ),
                            retained=state.retained_query_plan,
                            raw_question=planning_question,
                            follow_up_detected=state.context_follow_up_detected,
                        )
                    )

            logger.info("RetrieveContextNode completed successfully.")

            duration = (time.perf_counter() - start_time) * 1000

            # Return copied immutable Pydantic state
            return state.model_copy(
                update={
                    "database_context": db_context,
                    "query_plan": query_plan,
                    "current_node": "retrieve_context",
                    "completed_nodes": state.completed_nodes + ["retrieve_context"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "retrieve_context": duration},
                }
            )

        except Exception as e:
            logger.error(f"RetrieveContextNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"RetrieveContextNode failed: {e}"],
                    "current_node": "retrieve_context",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "retrieve_context": duration},
                }
            )

