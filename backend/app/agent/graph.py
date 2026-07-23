import logging

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.analyze_intent import AnalyzeIntentNode
from app.agent.nodes.analyze_results import AnalyzeResultsNode
from app.agent.nodes.execute_sql import ExecuteSQLNode
from app.agent.nodes.generate_chat_response import GenerateChatResponseNode
from app.agent.nodes.generate_clarification import GenerateClarificationNode
from app.agent.nodes.generate_help import GenerateHelpNode
from app.agent.nodes.generate_insights import GenerateInsightsNode
from app.agent.nodes.generate_observations import GenerateObservationsNode
from app.agent.nodes.generate_out_of_scope import GenerateOutOfScopeNode
from app.agent.nodes.generate_report import GenerateReportNode
from app.agent.nodes.generate_sql import GenerateSQLNode
from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.nodes.validate_sql import ValidateSQLNode
from app.agent.state import AgentState
from app.core.config import settings
from app.llm.interfaces import ILLMProvider
from app.services.interfaces import (
    IHelpService,
    IIntentClassifier,
    IPromptService,
    IWorkflowService,
)
from app.services.workflow_progress import with_progress

logger = logging.getLogger(__name__)


def route_by_intent(state: AgentState) -> str:
    """Routing function analyzing state.intent to direct graph traversal.

    Falls back to 'database_query' if the confidence is below the configured threshold,
    and logs structured observability metrics including the workflow ID and timing details.
    """
    intent_res = state.intent
    if not intent_res:
        return "unknown" if state.ambiguity is not None else "database_query"

    if intent_res.confidence < settings.INTENT_CONFIDENCE_THRESHOLD:
        decision = "database_query"
    else:
        decision = intent_res.intent.value

    # Ambiguous ranking phrases ("en iyi doktor") cannot be mapped to SQL
    # deterministically — divert to clarification instead of generating SQL.
    if decision == "database_query" and state.ambiguity is not None:
        decision = "unknown"

    # AG-022: database-bound questions with no schema-domain signal get
    # guided OUT_OF_SCOPE help instead of hallucinated SQL. The guard fails
    # open (answerable=None) so real questions are never blocked.
    if decision == "database_query" and state.answerable is False:
        decision = "out_of_scope"

    # Extract timing of analysis node
    elapsed_ms = state.node_timings.get("analyze_intent", 0.0)

    logger.info(
        "Intent Router Decision: workflow_id=%s elapsed_ms=%.2f question=%s "
        "detected_intent=%s confidence=%.2f matched_rule=%s "
        "final_routing_decision=%s matched_keywords=%s",
        state.workflow_id or "unknown",
        elapsed_ms,
        state.question,
        intent_res.intent.value,
        intent_res.confidence,
        intent_res.reason or "none",
        decision,
        intent_res.matched_keywords,
    )
    return decision


def route_after_value_resolution(state: AgentState) -> str:
    """Diverts to clarification when ResolveFilterValuesNode found an
    unresolved/ambiguous grounded filter mention (AI-INTELLIGENCE-016)."""
    return "clarify" if state.ambiguity is not None else "continue"


def route_after_validation(state: AgentState) -> str:
    """Skips DB execution when the user explicitly asked only for SQL."""
    if state.response_mode == "sql" and state.generated_sql is not None and not state.errors:
        logger.info(
            "Validation Router Decision: SQL-only output requested; skipping "
            "execution. workflow_id=%s",
            state.workflow_id or "unknown",
        )
        return "sql_only"
    return "execute"


def route_after_execution(state: AgentState) -> str:
    """Routes execute_sql output: one rewrite-and-retry on a retryable DB error (AG-022).

    ExecuteSQLNode marks a retryable failure by setting last_execution_error
    without appending to state.errors; everything else continues downstream,
    where empty/error handling produces guided responses.
    """
    if state.last_execution_error and state.sql_retry_count == 1 and not state.errors:
        logger.info(
            "Execution Router Decision: retrying SQL generation after execution "
            "failure. workflow_id=%s error=%s",
            state.workflow_id or "unknown",
            state.last_execution_error,
        )
        return "retry"
    if (
        state.response_mode == "data"
        and state.query_result is not None
        and not state.errors
        and not state.last_execution_error
    ):
        logger.info(
            "Execution Router Decision: data-only output requested; skipping "
            "analytics/report generation. workflow_id=%s",
            state.workflow_id or "unknown",
        )
        return "data_only"
    return "continue"


def route_after_analysis(state: AgentState) -> str:
    """Skips LLM insight/report stages when deterministic chart metadata is enough."""
    if (
        state.response_mode == "visualization"
        and state.query_result is not None
        and state.analytics is not None
        and not state.analytics_blocked_reason
        and not state.errors
    ):
        logger.info(
            "Analysis Router Decision: visualization-only output requested; "
            "skipping insight/report generation. workflow_id=%s",
            state.workflow_id or "unknown",
        )
        return "visualization_only"
    return "continue"


class AgentGraphBuilder:
    """Injects services, instantiates nodes, and compiles the agent graph."""

    def __init__(
        self,
        prompt_service: IPromptService,
        workflow_service: IWorkflowService,
        intent_classifier: IIntentClassifier | None = None,
        help_service: IHelpService | None = None,
        llm_provider: ILLMProvider | None = None,
    ):
        self.prompt_service = prompt_service
        self.workflow_service = workflow_service

        if intent_classifier is None:
            from app.services.intent_classifier import IntentClassifier

            intent_classifier = IntentClassifier()
        self.intent_classifier = intent_classifier

        if help_service is None:
            from app.services.help_service import HelpService

            help_service = HelpService()
        self.help_service = help_service

        if llm_provider is None:
            from app.llm.provider import LLMFactory

            llm_provider = LLMFactory.get_provider()
        self.llm_provider = llm_provider

    def build(self) -> CompiledStateGraph:
        """Assembles node topology and compiles the state graph."""
        logger.info("Starting agent graph construction via AgentGraphBuilder.")

        # 1. Instantiate workflow nodes
        analyze_intent_node = AnalyzeIntentNode(self.intent_classifier)
        chat_node = GenerateChatResponseNode(self.prompt_service, self.llm_provider)
        help_node = GenerateHelpNode(self.help_service)
        clarification_node = GenerateClarificationNode()
        out_of_scope_node = GenerateOutOfScopeNode()

        retrieve_node = RetrieveContextNode(self.prompt_service)
        resolve_values_node = ResolveFilterValuesNode()
        generate_node = GenerateSQLNode(self.workflow_service)
        validate_node = ValidateSQLNode()
        execute_node = ExecuteSQLNode(self.workflow_service)

        # DOCTOR-DISPLAY-NAME-ENRICHMENT-001: reuses the same read-only
        # repository already wired for analytical SQL execution — no new
        # database connection type, no parallel response system. Resolver is
        # optional: when the repository isn't available (e.g. a test double
        # workflow_service), analyze_results simply skips enrichment.
        doctor_label_resolver = None
        execution_service = getattr(self.workflow_service, "execution_service", None)
        repository = getattr(execution_service, "repository", None)
        if repository is not None:
            from app.services.doctor_label_resolver import DoctorLabelResolver

            doctor_label_resolver = DoctorLabelResolver(repository)
        analyze_results_node = AnalyzeResultsNode(doctor_label_resolver=doctor_label_resolver)
        from app.insights.insight_engine import InsightEngine
        from app.intelligence.observation_engine import ObservationEngine
        from app.llm.provider import LLMFactory

        # Complexity-based insight routing (deterministic / local-Ollama /
        # remote-NVIDIA): resolve both routing legs once at graph-build time,
        # sharing the same LLMFactory singletons used elsewhere. Either leg is
        # allowed to be unavailable — the router and InsightEngine's bounded
        # fallback both degrade gracefully when a leg is missing.
        local_insight_provider = None
        try:
            local_insight_provider = LLMFactory.get_provider(settings.INSIGHT_LOCAL_PROVIDER)
        except Exception as e:
            logger.warning(
                f"Insight routing: local provider '{settings.INSIGHT_LOCAL_PROVIDER}' "
                f"unavailable, deterministic-only fallback will apply: {e}"
            )
        remote_insight_provider = None
        if settings.NVIDIA_API_KEY.get_secret_value():
            try:
                remote_insight_provider = LLMFactory.get_provider(settings.INSIGHT_REMOTE_PROVIDER)
            except Exception as e:
                logger.warning(
                    f"Insight routing: remote provider '{settings.INSIGHT_REMOTE_PROVIDER}' "
                    f"unavailable, routing will stay local-only: {e}"
                )

        insights_node = GenerateInsightsNode(
            InsightEngine(
                llm_provider=self.llm_provider,
                local_llm_provider=local_insight_provider,
                remote_llm_provider=remote_insight_provider,
            )
        )
        observations_node = GenerateObservationsNode(
            ObservationEngine(
                llm_provider=self.llm_provider,
                use_llm_wording=settings.OBSERVATION_LLM_WORDING,
            )
        )
        report_node = GenerateReportNode(self.workflow_service)

        # 2. Build StateGraph using the IAgentNode.execute method wrappers
        workflow = StateGraph(AgentState)

        workflow.add_node(
            "analyze_intent", with_progress("understanding", analyze_intent_node.execute)
        )
        workflow.add_node("generate_chat_response", with_progress("reporting", chat_node.execute))
        workflow.add_node("generate_help", with_progress("reporting", help_node.execute))
        workflow.add_node(
            "generate_clarification", with_progress("reporting", clarification_node.execute)
        )
        workflow.add_node(
            "generate_out_of_scope", with_progress("reporting", out_of_scope_node.execute)
        )

        workflow.add_node("retrieve_context", with_progress("preparing_sql", retrieve_node.execute))
        workflow.add_node(
            "resolve_filter_values", with_progress("preparing_sql", resolve_values_node.execute)
        )
        workflow.add_node("generate_sql", with_progress("preparing_sql", generate_node.execute))
        workflow.add_node("validate_sql", with_progress("validating_sql", validate_node.execute))
        workflow.add_node("execute_sql", with_progress("executing_sql", execute_node.execute))
        workflow.add_node(
            "analyze_results", with_progress("analyzing_data", analyze_results_node.execute)
        )
        workflow.add_node(
            "generate_insights", with_progress("analyzing_data", insights_node.execute)
        )
        workflow.add_node(
            "generate_observations", with_progress("reporting", observations_node.execute)
        )
        workflow.add_node("generate_report", with_progress("reporting", report_node.execute))

        # 3. Add Edges & Conditional Routing
        workflow.add_edge(START, "analyze_intent")

        workflow.add_conditional_edges(
            "analyze_intent",
            route_by_intent,
            {
                "database_query": "retrieve_context",
                "general_chat": "generate_chat_response",
                "help": "generate_help",
                "unknown": "generate_clarification",
                "out_of_scope": "generate_out_of_scope",
            },
        )

        # Direct shortcuts to END
        workflow.add_edge("generate_chat_response", END)
        workflow.add_edge("generate_help", END)
        workflow.add_edge("generate_clarification", END)
        workflow.add_edge("generate_out_of_scope", END)

        # Standard SQL execution pipeline
        workflow.add_edge("retrieve_context", "resolve_filter_values")
        workflow.add_conditional_edges(
            "resolve_filter_values",
            route_after_value_resolution,
            {
                "clarify": "generate_clarification",
                "continue": "generate_sql",
            },
        )
        workflow.add_edge("generate_sql", "validate_sql")
        workflow.add_conditional_edges(
            "validate_sql",
            route_after_validation,
            {
                "sql_only": END,
                "execute": "execute_sql",
            },
        )

        # AG-022: a retryable execution failure loops back to SQL generation
        # exactly once, feeding the database error into the regeneration prompt.
        workflow.add_conditional_edges(
            "execute_sql",
            route_after_execution,
            {
                "retry": "generate_sql",
                "data_only": END,
                "continue": "analyze_results",
            },
        )
        workflow.add_conditional_edges(
            "analyze_results",
            route_after_analysis,
            {
                "visualization_only": END,
                "continue": "generate_insights",
            },
        )
        workflow.add_edge("generate_insights", "generate_observations")
        workflow.add_edge("generate_observations", "generate_report")
        workflow.add_edge("generate_report", END)

        logger.info("Agent graph constructed and compiled successfully.")
        return workflow.compile()
