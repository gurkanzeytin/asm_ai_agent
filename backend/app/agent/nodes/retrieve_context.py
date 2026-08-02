import logging
import time
from calendar import monthrange
from datetime import date, timedelta

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.schema_reasoning import SchemaReasoningDecision
from app.context.analytical_signals import dedupe_date_filters, merge_query_plans
from app.planning.models import DateFilterPlan, PlannedDimension, PlannedMetric, QueryPlan
from app.planning.planner import QueryPlanner
from app.semantics import catalog
from app.semantics.view_mapping import fold
from app.services.interfaces import IPromptService
from app.services.query_analyzer import QueryAnalyzer

logger = logging.getLogger(__name__)

_OUTPUT_ACTION_MARKERS = ("sql", "sorgu")
_SCHEMA_REASONING_SIGNAL = "schema_reasoning:answerable"


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

    @staticmethod
    def _date_filter_from_scope(
        scope: str | None,
        column: str,
        *,
        today: date | None = None,
    ) -> DateFilterPlan | None:
        if not scope or scope == "all_time":
            return None
        current = today or date.today()
        if scope == "current_day":
            start = end = current
        elif scope == "previous_day":
            start = end = current - timedelta(days=1)
        elif scope == "current_week":
            start = current - timedelta(days=current.weekday())
            end = start + timedelta(days=6)
        elif scope == "previous_week":
            start = current - timedelta(days=current.weekday() + 7)
            end = start + timedelta(days=6)
        elif scope == "current_month":
            start = current.replace(day=1)
            end = current.replace(day=monthrange(current.year, current.month)[1])
        elif scope == "previous_month":
            end = current.replace(day=1) - timedelta(days=1)
            start = end.replace(day=1)
        elif scope == "current_year":
            start, end = date(current.year, 1, 1), date(current.year, 12, 31)
        elif scope == "previous_year":
            start, end = date(current.year - 1, 1, 1), date(current.year - 1, 12, 31)
        elif scope == "last_7_days":
            start, end = current - timedelta(days=6), current
        elif scope == "last_30_days":
            start, end = current - timedelta(days=29), current
        else:
            return None
        return DateFilterPlan(
            expression=f"schema_reasoning:{scope}",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            column=column,
        )

    @staticmethod
    def _typed_schema_plan(
        question: str,
        decision: SchemaReasoningDecision,
        db_context,
        base_plan: QueryPlan | None,
    ) -> QueryPlan | None:
        if not decision.typed_plan_ready:
            return None
        metric_by_id = catalog.load_metric_catalog().by_id()
        metrics = list(decision.supporting_metrics)
        dimensions = list(decision.dimension_columns)
        required_columns = catalog.required_columns_for(metrics, dimensions)
        if decision.time_column and decision.time_column not in required_columns:
            required_columns.append(decision.time_column)

        planned_metrics = [
            PlannedMetric(
                metric_id=metric.id,
                aggregation_type=metric.formula_type,
                format_type=metric.result_type,
                source_columns=list(metric.required_columns),
            )
            for metric_id in metrics
            if (metric := metric_by_id.get(metric_id)) is not None
        ]
        from app.context.analytical_signals import column_to_dimension

        planned_dimensions = [
            PlannedDimension(
                column=column,
                canonical_name=column_to_dimension(column),
            )
            for column in dimensions
        ]
        primary = metric_by_id.get(metrics[0]) if len(metrics) == 1 else None
        view_name = db_context.views[0].name if db_context.views else None
        date_filters = list(base_plan.date_filters) if base_plan else []
        periods = list(base_plan.periods) if base_plan else []
        if decision.time_scope == "all_time":
            date_filters, periods = [], []
        elif decision.time_scope:
            time_column = decision.time_column or "BaslangicTarihi"
            resolved = RetrieveContextNode._date_filter_from_scope(
                decision.time_scope, time_column
            )
            date_filters = [resolved] if resolved else []
            periods = []

        assumptions = [
            *decision.assumptions,
            "Soru, katalog dışı söyleyiş nedeniyle doğrulanmış LLM şema planıyla çözüldü.",
        ]
        return QueryPlan(
            question=question,
            planning_source="llm_schema_reasoning",
            output_entity="Appointment",
            fact_entity="Appointment",
            output_table=view_name,
            fact_table=view_name,
            date_filters=date_filters,
            periods=periods,
            aggregation=primary.formula if primary else None,
            ranking=decision.order,
            order=decision.order,
            limit=decision.limit,
            analysis_type=decision.analysis_type,
            projection=dimensions[:2],
            metrics=metrics,
            dimensions=dimensions,
            planned_metrics=planned_metrics,
            planned_dimensions=planned_dimensions,
            grouping_granularity=decision.grouping_granularity,
            required_columns=required_columns,
            answerable=True,
            confidence=decision.confidence,
            assumptions=assumptions,
            planner_ms=base_plan.planner_ms if base_plan else 0.0,
        )

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("RetrieveContextNode execution started.")
        start_time = time.perf_counter()

        try:
            db_context = await self.prompt_service.retrieve_schema_context(state.question)
            planning_question = state.raw_question or state.question
            if state.answerability_input and state.answerability_input.pending_clarification:
                # A pending-clarification reply ("Genel Cerrahi'yi kastettim")
                # carries almost none of the original analytical content on
                # its own - ContextResolver._resolve_pending_value_clarification
                # already replayed the FULL original question into
                # state.question (raw_question is just the disambiguating
                # reply). Planning from raw_question here, as a normal terse
                # follow-up correctly does to see only THIS turn's explicit
                # signals, would build a near-empty plan from just the reply
                # text and then silently inherit an unrelated metric from
                # whatever plan was last SUCCESSFULLY persisted (an
                # ASK_CLARIFICATION turn never updates session memory) -
                # not from the turn that actually asked the question
                # (2026-07-24, live multi-turn testing: answering a
                # department-name clarification returned a completely
                # different, two-turns-back question's metric).
                planning_question = state.question
            planning_frame = None if state.context_follow_up_detected else state.semantic_frame
            query_plan = self._build_plan(planning_question, db_context, planning_frame)
            current_turn_has_date = bool(query_plan.date_filters) if query_plan else False
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

            # A follow-up plans from the raw text ("Peki Temmuz ayında?") so the
            # merge only sees this turn's explicit signals — but a bare month
            # there carries no year and defaults to today's. The context
            # resolver already re-anchored the year inside the resolved
            # question ("2025 temmuz ..."), so its date span is authoritative.
            # Only applies when this turn itself mentions a date; otherwise the
            # merge-inherited filter (incl. its column choice) must survive.
            period_direction_only_followup = (
                query_plan is not None
                and bool(query_plan.periods)
                and not current_turn_has_date
                and catalog.period_change_direction(fold(planning_question)) is not None
            )
            if (
                query_plan is not None
                and state.context_follow_up_detected
                and state.question != planning_question
                and not period_direction_only_followup
                and not all(marker in fold(planning_question) for marker in _OUTPUT_ACTION_MARKERS)
            ):
                resolved_plan = self._build_plan(state.question, db_context, None)
                if resolved_plan is not None and resolved_plan.date_filters:
                    if resolved_plan.periods or resolved_plan.analysis_type in {
                        "period_comparison",
                        "baseline_comparison",
                        "adaptive_time_comparison",
                        "percentage_change",
                    }:
                        query_plan = merge_query_plans(
                            current=resolved_plan,
                            retained=state.retained_query_plan,
                            raw_question=state.question,
                            follow_up_detected=state.context_follow_up_detected,
                        )
                    else:
                        # `resolved_plan` is planned from the RESOLVED question,
                        # which prepends the previous turn — so it re-detects
                        # every date mentioned earlier too. Normalise before
                        # adopting them, or a broad early scope ("2022-2025
                        # arasında …") keeps riding along with the narrower
                        # years later turns name, and the window list grows
                        # every turn (Codex live UI testing, 2026-07-31).
                        query_plan = query_plan.model_copy(
                            update={
                                "date_filters": dedupe_date_filters(
                                    list(resolved_plan.date_filters)
                                ),
                                "periods": [],
                                "current_period": None,
                                "baseline_period": None,
                            }
                        )

            # The deterministic planner already failed to recognize this turn's
            # wording. Prefer the validated typed schema plan; if the LLM could
            # establish only answerability (no metric/analysis contract), release
            # the weak deterministic plan and use the existing schema-only path.
            if _SCHEMA_REASONING_SIGNAL in state.answerability_signals:
                query_plan = self._typed_schema_plan(
                    state.question,
                    state.schema_reasoning_decision,
                    db_context,
                    query_plan,
                ) if state.schema_reasoning_decision is not None else None
                logger.info(
                    "RetrieveContextNode selected schema reasoning SQL fallback.",
                    extra={
                        "typed_plan": query_plan is not None,
                        "planning_source": (
                            query_plan.planning_source if query_plan else "schema_only"
                        ),
                    },
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
