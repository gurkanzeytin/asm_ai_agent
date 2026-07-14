import logging
import uuid
from typing import Any, Optional

from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.application_models.query_analysis import AmbiguityResult
from app.application_models.workflow_metrics import WorkflowMetrics
from app.application_models.workflow_result import WorkflowResult
from app.context import ContextManager

logger = logging.getLogger(__name__)

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
        context_manager: Optional[ContextManager] = None,
    ) -> None:
        """Initializes the service with the pre-compiled LangGraph state machine.

        Args:
            agent_graph: Compiled LangGraph CompiledStateGraph instance.
            context_manager: Conversational context engine (PRODUCT-001). A
                default instance is created when omitted.
        """
        self._agent_graph = agent_graph
        self._context_manager = context_manager or ContextManager()

    async def run_workflow(
        self, question: str, session_id: Optional[str] = "default"
    ) -> WorkflowResult:
        """Runs the full agent graph pipeline and returns a typed WorkflowResult.

        Args:
            question: Natural-language question submitted by the user.
            session_id: Conversational session key for follow-up resolution.
                Pass None to bypass the context engine entirely (e.g. benchmarks).

        Returns:
            WorkflowResult: Typed DTO containing all workflow outputs including metrics.

        Raises:
            Domain exceptions from the service layer are intentionally propagated
            so that the global exception handlers can map them to HTTP responses.
        """
        workflow_id = str(uuid.uuid4())
        logger.info(f"ReportingService: Starting workflow run [{workflow_id}] for question: {question!r}")

        # Conversational context resolution (PRODUCT-001): rewrite follow-up
        # questions using session context before the NLU pipeline runs.
        resolution = None
        pipeline_question = question
        seeded_ambiguity = None
        if session_id is not None:
            resolution = self._context_manager.resolve(question, session_id)
            if resolution.clarification_needed:
                seeded_ambiguity = AmbiguityResult(
                    matched_phrase=question,
                    question=resolution.clarification_question or "",
                    options=resolution.clarification_options,
                )
            else:
                pipeline_question = resolution.resolved_question

        initial_state = AgentState(
            question=pipeline_question,
            workflow_id=workflow_id,
            ambiguity=seeded_ambiguity,
        )

        # Run compiled LangGraph workflow pipeline — domain exceptions propagate upward
        final_state = await self._agent_graph.ainvoke(initial_state)

        if resolution is not None and session_id is not None:
            self._context_manager.update(resolution, session_id)

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

        # Build typed WorkflowMetrics from per-node timing accumulator
        sql_latency = generated_sql_dto.latency_ms if generated_sql_dto else 0.0
        report_latency = generated_report_dto.latency_ms if generated_report_dto else 0.0
        llm_total_ms = sql_latency + report_latency if (sql_latency or report_latency) else None

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
            f"ReportingService: Workflow [{workflow_id}] executed using Provider [{active_provider}] Model [{active_model}]"
        )

        logger.info(
            f"ReportingService: Workflow [{workflow_id}] errors: {errors or 'none'}"
        )

        return WorkflowResult(
            workflow_id=workflow_id,
            question=question,
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
        )


def _fmt_ms(value: float | None) -> str:
    """Formats a millisecond value for the timing summary table."""
    if value is None:
        return "    —    "
    if value >= 1000:
        return f"{value / 1000:.1f} s"
    return f"{value:.0f} ms"
