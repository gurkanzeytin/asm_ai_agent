import logging
import uuid
from typing import Any

from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.application_models.query_analysis import AmbiguityResult
from app.application_models.workflow_metrics import WorkflowMetrics
from app.application_models.workflow_result import WorkflowResult
from app.context import ContextManager
from app.context import analytical_signals as _analytical_signals
from app.context.analysis_type import resolve_canonical_analysis_type
from app.context.analytical_signals import FILTER_FAMILIES as _FILTER_FAMILIES
from app.context.session_store import generate_session_id
from app.planning.models import QueryPlan
from app.services.answerability import AnswerabilityInput
from app.services.workflow_progress import (
    ProgressCallback,
    reset_progress_callback,
    set_progress_callback,
)

logger = logging.getLogger(__name__)

# Memory write policy (Part 7): conversational context is only persisted after
# a genuinely successful, data-bearing workflow outcome. Every other terminal
# outcome (clarification, out-of-scope, help, a retry loop that never
# resolved, or the synthetic SAFE_ERROR fallback) must never overwrite
# previously valid context with an incomplete/failed turn's signals.
_MEMORY_WRITE_ELIGIBLE_OUTCOMES = frozenset(
    {AgentOutcome.EXECUTE_SQL.value, AgentOutcome.NO_RESULT_GUIDANCE.value}
)

# Sentinel distinguishing "session_id truly omitted" (generate an isolated
# ephemeral session) from "session_id=None passed explicitly" (bypass the
# context engine entirely — the existing, deliberate benchmark/eval-harness
# contract). A plain default value can't call uuid4() per-call, so the actual
# generation happens once inside run_workflow when this sentinel is seen.
_UNSET = object()

# AG-022 SAFE_ERROR: friendly, non-technical guidance shown when the pipeline
# could not produce any report. Guarantees the user never sees an empty or
# generic failure response.
_SAFE_ERROR_MARKDOWN = """# Yanıt Oluşturulamadı

Sorunuzu işlerken beklenmedik bir sorunla karşılaştım. Bu sizin hatanız değil.

## Ne yapabilirsiniz?

- Soruyu birkaç saniye sonra tekrar gönderin.
- Soruyu daha kısa ve tek bir konu üzerinde olacak şekilde yeniden ifade edin.
- Örnek bir kalıp deneyin: "Bugün kaç randevu oluşturuldu?", "Kardiyoloji doktorlarını göster."

Sorun devam ederse sistem yöneticinize başvurabilirsiniz.
"""


class ReportingService:
    """Orchestrates the complete AI reporting workflow by invoking the compiled agent graph.

    Acts as the sole entry point for the API layer. All internal DTOs are mapped into
    a typed WorkflowResult before returning; no internal model is leaked to the transport layer.
    """

    def __init__(
        self,
        agent_graph: Any,
        context_manager: ContextManager | None = None,
    ) -> None:
        """Initializes the service with the pre-compiled LangGraph state machine.

        Args:
            agent_graph: Compiled LangGraph CompiledStateGraph instance.
            context_manager: Conversational context engine (PRODUCT-001). A
                default instance is created when omitted.
        """
        self._agent_graph = agent_graph
        self._context_manager = context_manager or ContextManager()

    @staticmethod
    def _pending_value_clarification_field(query_plan_dto):
        """Returns the first `resolved_filters` entry still awaiting clarification
        (AI-INTELLIGENCE-016/017), or None. Deterministic order (dict insertion)."""
        if query_plan_dto is None:
            return None
        for resolved_filter in query_plan_dto.resolved_filters.values():
            if resolved_filter.clarification_required:
                return resolved_filter
        return None

    async def run_workflow(
        self,
        question: str,
        session_id: str | None = _UNSET,
        progress_callback: ProgressCallback | None = None,
    ) -> WorkflowResult:
        """Runs the full agent graph pipeline and returns a typed WorkflowResult.

        Args:
            question: Natural-language question submitted by the user.
            session_id: Conversational session key for follow-up resolution.
                Pass None to bypass the context engine entirely (e.g. benchmarks,
                evaluation-harness cases that must never share memory). Omit
                entirely to get a fresh, isolated ephemeral session per call —
                this never silently pools unrelated callers into one shared
                "default" session (see app.context.session_store.generate_session_id).

        Returns:
            WorkflowResult: Typed DTO containing all workflow outputs including metrics.

        Raises:
            Domain exceptions from the service layer are intentionally propagated
            so that the global exception handlers can map them to HTTP responses.
        """
        workflow_id = str(uuid.uuid4())
        if session_id is _UNSET:
            session_id = generate_session_id()
        logger.info(
            f"ReportingService: Starting workflow run [{workflow_id}] for question: {question!r}"
        )

        # Conversational context resolution (PRODUCT-001): rewrite follow-up
        # questions using session context before the NLU pipeline runs.
        resolution = None
        pipeline_question = question
        seeded_ambiguity = None
        memory_expired = False
        if session_id is not None:
            memory_expired = self._context_manager.is_expired_or_absent(session_id)
            resolution = self._context_manager.resolve(question, session_id)
            if resolution.clarification_needed:
                seeded_ambiguity = AmbiguityResult(
                    matched_phrase=question,
                    question=resolution.clarification_question or "",
                    options=resolution.clarification_options,
                )
            else:
                pipeline_question = resolution.resolved_question

        answerability_context_signals: list[str] = []
        answerability_input_source = "raw_question"
        if resolution is not None and resolution.context_applied:
            answerability_input_source = "resolved_context"
            answerability_context_signals.extend(
                f"inherited_entity:{entity}"
                for entity in self._context_manager.entity_types(session_id)
            )
            answerability_context_signals.extend(
                f"inherited_metric:{metric}"
                for metric in resolution.resolved_signals.metrics
            )
            explicit_date = self._context_manager.extract_date(question)
            if explicit_date:
                answerability_context_signals.append(f"explicit_date:{explicit_date}")

        # AI-INTELLIGENCE-018 (item 2): typed answerability decision contract
        # — a short follow-up is evaluated against the RESOLVED analytical
        # context (metrics/dimensions actually merged this turn), not raw
        # text alone or a loosely-typed signal-string list.
        answerability_input = None
        if resolution is not None:
            answerability_input = AnswerabilityInput(
                raw_question=question,
                resolved_question=pipeline_question,
                has_valid_prior_context=resolution.context_applied,
                resolved_metrics=list(resolution.resolved_signals.metrics),
                resolved_dimensions=list(resolution.resolved_signals.dimensions),
                resolved_date_range=(
                    self._context_manager.extract_date(question)
                    or (resolution.inherited.get("date") if resolution.context_applied else None)
                ),
                context_operation=(
                    resolution.follow_up_signals[0] if resolution.follow_up_signals else None
                ),
                pending_clarification=resolution.pending_clarification_resolved,
            )

        initial_state = AgentState(
            question=pipeline_question,
            raw_question=question,
            workflow_id=workflow_id,
            ambiguity=seeded_ambiguity,
            answerability_input_source=answerability_input_source,
            answerability_context_signals=answerability_context_signals,
            answerability_input=answerability_input,
            forced_filter_override=(resolution.filter_override if resolution else {}),
            retained_query_plan=(
                QueryPlan.model_validate(resolution.retained_query_plan_snapshot)
                if resolution is not None and resolution.retained_query_plan_snapshot
                else None
            ),
            context_follow_up_detected=(
                resolution.follow_up_detected if resolution is not None else False
            ),
        )

        # ContextVar keeps progress request-scoped while the graph is shared.
        progress_token = set_progress_callback(progress_callback)
        try:
            final_state = await self._agent_graph.ainvoke(initial_state)
        finally:
            reset_progress_callback(progress_token)

        generated_sql_dto = final_state.get("generated_sql")
        query_result_dto = final_state.get("query_result")
        generated_report_dto = final_state.get("generated_report")
        intent_dto = final_state.get("intent")
        analytics_dto = final_state.get("analytics")
        insights_dto = final_state.get("insights")
        observations_dto = final_state.get("observations")
        errors = final_state.get("errors", [])
        node_timings: dict[str, float] = final_state.get("node_timings") or {}
        outcome = final_state.get("outcome")
        query_plan_dto = final_state.get("query_plan")
        semantic_frame_dto = final_state.get("semantic_frame")

        # AG-022 SAFE_ERROR: the workflow must never end without a user-facing
        # response. If no node produced a report, synthesize friendly guidance.
        if generated_report_dto is None:
            logger.warning(
                "ReportingService: Workflow [%s] produced no report "
                "(errors: %s) — returning SAFE_ERROR guidance.",
                workflow_id,
                errors or "none",
            )
            generated_report_dto = GeneratedReport(
                title="Yanıt Oluşturulamadı",
                markdown=_SAFE_ERROR_MARKDOWN,
                provider="static",
                model="safe_error_fallback",
                latency_ms=0.0,
            )
            outcome = AgentOutcome.SAFE_ERROR.value

        # Memory write policy (Part 7): only persist conversational context after
        # a genuinely successful, data-bearing outcome. A validation failure,
        # execution failure, out-of-scope verdict, unresolved clarification, or
        # the synthetic SAFE_ERROR fallback must never overwrite previously
        # valid context with an incomplete/failed turn's signals.
        memory_updated = False
        memory_turn_count: int | None = None
        if resolution is not None and session_id is not None:
            should_persist_memory = (
                not resolution.clarification_needed
                and not errors
                and outcome in _MEMORY_WRITE_ELIGIBLE_OUTCOMES
                and query_result_dto is not None
            )
            if should_persist_memory:
                canonical_analysis_type = resolve_canonical_analysis_type(
                    analytics_type=analytics_dto.analytics_type if analytics_dto else None,
                    outcome=outcome,
                )
                memory_updated = self._context_manager.update(
                    resolution,
                    session_id,
                    canonical_analysis_type=canonical_analysis_type,
                    query_plan=query_plan_dto,
                )
            elif outcome == AgentOutcome.ASK_CLARIFICATION.value:
                # Bounded pending clarification (Part 7): touches only
                # pending_clarification; every other valid context field is
                # left completely untouched.
                pending_value_field = self._pending_value_clarification_field(query_plan_dto)
                if pending_value_field is not None:
                    # AI-INTELLIGENCE-016/017: an ambiguous/no-match grounded
                    # value mention (app.planning.value_resolver). Persist
                    # enough typed context (item 7) that a later "hepsini" /
                    # ordinal / explicit reply can resume the ORIGINAL
                    # analytical request without losing its intent.
                    self._context_manager.set_pending_clarification(
                        session_id,
                        field=f"value_filter:{pending_value_field.field}",
                        reason=pending_value_field.clarification_message or "ambiguous value",
                        choices=pending_value_field.alternatives,
                        original_question=pipeline_question,
                        candidate_values=pending_value_field.alternatives,
                        original_analysis_type=(
                            query_plan_dto.analysis_type if query_plan_dto else None
                        ),
                        original_metrics=query_plan_dto.metrics if query_plan_dto else [],
                        original_dimensions=query_plan_dto.dimensions if query_plan_dto else [],
                        original_date_expression=(
                            query_plan_dto.date_filters[0].expression
                            if query_plan_dto and query_plan_dto.date_filters
                            else None
                        ),
                        original_filters=(
                            {
                                field: fr.values
                                for field, fr in query_plan_dto.resolved_filters.items()
                                if fr.grounded and field != pending_value_field.field
                            }
                            if query_plan_dto
                            else {}
                        ),
                    )
                elif semantic_frame_dto is not None:
                    # An ambiguous ranking phrase ("en iyi", "en verimli", ...)
                    # the semantic engine already flagged
                    # (app.semantics.ontology.AMBIGUOUS_PHRASES) — reused
                    # verbatim, never re-detected here.
                    ambiguities = getattr(semantic_frame_dto, "ambiguities", None) or []
                    if ambiguities:
                        first = ambiguities[0]
                        self._context_manager.set_pending_clarification(
                            session_id,
                            field="ranking_metric",
                            reason=first.reason,
                            choices=[],
                        )
            memory_turn_count = self._context_manager.turn_count(session_id)
            pending_clarification = self._context_manager.get_pending_clarification(session_id)
        else:
            pending_clarification = None

        # Build typed WorkflowMetrics from per-node timing accumulator.
        #
        # llm_total_ms must sum every stage that can call an LLM, not just SQL/
        # report generation — the Insight and Observation Engines also make their
        # own LLM calls (InsightResult.llm_latency_ms / ObservationResult.llm_latency_ms),
        # and those calls are real (can take seconds) even though the report stage
        # that reuses their narrative finishes in under a millisecond. Omitting them
        # here previously made the "LLM Inference" summary report ~0ms even when the
        # Insight Engine's own LLM call took 8-58s.
        sql_latency = generated_sql_dto.latency_ms if generated_sql_dto else 0.0
        report_latency = generated_report_dto.latency_ms if generated_report_dto else 0.0
        insight_llm_latency = insights_dto.llm_latency_ms if insights_dto else None
        observation_llm_latency = observations_dto.llm_latency_ms if observations_dto else None
        llm_total_ms = (
            sql_latency
            + report_latency
            + (insight_llm_latency or 0.0)
            + (observation_llm_latency or 0.0)
            if (sql_latency or report_latency or insight_llm_latency or observation_llm_latency)
            else None
        )

        metrics = WorkflowMetrics(
            retrieve_context_ms=node_timings.get("retrieve_context"),
            generate_sql_ms=node_timings.get("generate_sql"),
            validate_sql_ms=node_timings.get("validate_sql"),
            execute_sql_ms=node_timings.get("execute_sql"),
            generate_report_ms=node_timings.get("generate_report"),
            analyze_intent_ms=node_timings.get("analyze_intent"),
            analyze_results_ms=node_timings.get("analyze_results"),
            generate_insights_ms=node_timings.get("generate_insights"),
            generate_observations_ms=node_timings.get("generate_observations"),
            insight_llm_ms=insight_llm_latency,
            observation_llm_ms=observation_llm_latency,
            llm_total_ms=llm_total_ms,
            total_ms=sum(node_timings.values()),
        )

        # Log timing summary
        logger.info(
            "ReportingService: Workflow [%s] completed.\n"
            "  ┌─────────────────────────┬─────────────┐\n"
            "  │ Stage                   │ Duration    │\n"
            "  ├─────────────────────────┼─────────────┤\n"
            "  │ Analyze Intent          │ %9s  │\n"
            "  │ Retrieve Context        │ %9s  │\n"
            "  │ Generate SQL            │ %9s  │\n"
            "  │ Validate SQL            │ %9s  │\n"
            "  │ Execute SQL             │ %9s  │\n"
            "  │ Analytics Engine        │ %9s  │\n"
            "  │ Insight Engine          │ %9s  │\n"
            "  │ Observation Engine      │ %9s  │\n"
            "  │ Generate Report         │ %9s  │\n"
            "  ├─────────────────────────┼─────────────┤\n"
            "  │ Total                   │ %9s  │\n"
            "  │ LLM Inference           │ %9s  │\n"
            "  └─────────────────────────┴─────────────┘",
            workflow_id,
            _fmt_ms(metrics.analyze_intent_ms),
            _fmt_ms(metrics.retrieve_context_ms),
            _fmt_ms(metrics.generate_sql_ms),
            _fmt_ms(metrics.validate_sql_ms),
            _fmt_ms(metrics.execute_sql_ms),
            _fmt_ms(metrics.analyze_results_ms),
            _fmt_ms(metrics.generate_insights_ms),
            _fmt_ms(metrics.generate_observations_ms),
            _fmt_ms(metrics.generate_report_ms),
            _fmt_ms(metrics.total_ms),
            _fmt_ms(metrics.llm_total_ms),
        )

        # Determine active provider and model name if LLM was invoked
        active_provider = "unknown"
        active_model = "unknown"
        if generated_report_dto:
            active_provider = generated_report_dto.provider
            active_model = generated_report_dto.model
        elif generated_sql_dto:
            active_provider = generated_sql_dto.provider
            active_model = generated_sql_dto.model
        else:
            # Fall back to settings-configured provider
            from app.core.config import settings

            active_provider = settings.LLM_PROVIDER
            if active_provider == "gemini":
                active_model = settings.GEMINI_MODEL
            else:
                active_model = settings.OLLAMA_MODEL

        logger.info(
            "ReportingService: Workflow [%s] executed using Provider [%s] Model [%s]",
            workflow_id,
            active_provider,
            active_model,
        )

        logger.info(f"ReportingService: Workflow [{workflow_id}] errors: {errors or 'none'}")

        return WorkflowResult(
            workflow_id=workflow_id,
            question=question,
            raw_question=question,
            resolved_question=resolution.resolved_question if resolution else question,
            answerability_input_source=final_state.get(
                "answerability_input_source", answerability_input_source
            ),
            answerability_signals=final_state.get("answerability_signals", []),
            generated_sql=generated_sql_dto.sql if generated_sql_dto else None,
            query_result=query_result_dto,
            generated_report=generated_report_dto,
            errors=errors,
            metrics=metrics,
            intent=intent_dto,
            analytics=analytics_dto,
            insights=insights_dto,
            observations=observations_dto,
            outcome=outcome,
            session_id=session_id,
            follow_up_detected=resolution.follow_up_detected if resolution else False,
            follow_up_confidence=resolution.follow_up_confidence if resolution else 1.0,
            follow_up_signals=resolution.follow_up_signals if resolution else [],
            context_applied=resolution.context_applied if resolution else False,
            inherited_fields=list(resolution.inherited.keys()) if resolution else [],
            overridden_fields=resolution.overridden_fields if resolution else [],
            memory_updated=memory_updated,
            memory_turn_count=memory_turn_count,
            memory_expired=memory_expired,
            explicit_context_fields=resolution.explicit_fields if resolution else [],
            inherited_context_fields=list(resolution.inherited.keys()) if resolution else [],
            overridden_context_fields=resolution.overridden_fields if resolution else [],
            removed_context_fields=resolution.removed_fields if resolution else [],
            resolved_metrics=resolution.resolved_signals.metrics if resolution else [],
            resolved_dimensions=resolution.resolved_signals.dimensions if resolution else [],
            resolved_filters=(
                {
                    family: getattr(resolution.resolved_signals, family)
                    for family in _FILTER_FAMILIES
                }
                if resolution
                else {}
            ),
            # AI-INTELLIGENCE-018 (item 6): the QueryPlan's own
            # grouping_granularity (already resolved during planning, and the
            # one actually used to build/execute this turn's SQL) is
            # authoritative — falls back to the pre-graph raw-text/inherited
            # signal only when no plan was built at all (e.g. clarification).
            resolved_time_grain=(
                _analytical_signals.granularity_to_time_grain(query_plan_dto.grouping_granularity)
                if query_plan_dto is not None and query_plan_dto.grouping_granularity
                else (resolution.resolved_signals.time_grain if resolution else None)
            ),
            resolved_ranking=resolution.resolved_signals.ranking if resolution else None,
            resolved_limit=resolution.resolved_signals.limit if resolution else None,
            pending_clarification_field=(
                pending_clarification.field if pending_clarification else None
            ),
        )


def _fmt_ms(value: float | None) -> str:
    """Formats a millisecond value for the timing summary table."""
    if value is None:
        return "    —    "
    if value >= 1000:
        return f"{value / 1000:.1f} s"
    return f"{value:.0f} ms"
