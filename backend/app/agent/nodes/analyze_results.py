import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.result_contracts import TypedResultNormalizer
from app.analytics.result_reasoning import ResultReasoner
from app.analytics.result_validation import ResultValidator
from app.services.result_safety import enrich_result_counts, is_unsafe_analytical_detail
from app.shared.result_limits import OVERSIZED_ANALYTICAL_RESULT_MESSAGE

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

        # An invalid result shape (missing/renamed expected columns — never a
        # legitimate all-zero result) must never reach analytics/insight
        # routing/report generation as if it were a normal success: skip
        # analytics entirely and record why, so downstream nodes can produce a
        # safe clarification instead of fabricating insight over a
        # structurally wrong result.
        if state.result_shape_verdict is not None and not state.result_shape_verdict.valid:
            logger.warning(
                "AnalyzeResultsNode skipped: invalid result shape (%s).",
                state.result_shape_verdict.reason,
            )
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "analytics_blocked_reason": state.result_shape_verdict.reason,
                    "current_node": "analyze_results",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "analyze_results": duration},
                }
            )

        if is_unsafe_analytical_detail(state.query_result, state.query_plan):
            logger.warning(
                "AnalyzeResultsNode blocked oversized identifier-bearing analytical detail."
            )
            duration = (time.perf_counter() - start_time) * 1000
            guarded_result = state.query_result.model_copy(
                update={"unsafe_detail_output": True}
            )
            return state.model_copy(
                update={
                    "query_result": guarded_result,
                    "analytics_blocked_reason": OVERSIZED_ANALYTICAL_RESULT_MESSAGE,
                    "current_node": "analyze_results",
                    "completed_nodes": state.completed_nodes + ["analyze_results"],
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

            normalizer = TypedResultNormalizer()
            normalized = normalizer.normalize(
                state.query_result,
                plan=state.query_plan,
                schema_name=state.generated_sql.result_schema if state.generated_sql else None,
                expected_aliases=state.generated_sql.expected_aliases if state.generated_sql else None,
            )
            query_result = normalizer.as_query_result(state.query_result, normalized)

            metric_aliases = state.generated_sql.metric_aliases if state.generated_sql else None
            analytics_result = self.analytics_engine.analyze(
                question, query_result, plan=state.query_plan, metric_aliases=metric_aliases
            )
            query_result = enrich_result_counts(query_result, analytics_result)

            # AI-INTELLIGENCE-008: deterministic result reasoning (baseline delta,
            # low-sample flags, top findings) rides on the analytics insights dict
            # so the narrative layers downstream can surface it.
            reasoning_outcome = ResultReasoner().reason(
                query_result,
                plan=state.query_plan,
                result_schema=normalized.schema_name,
                warnings=normalized.warnings,
            )
            if reasoning_outcome.findings or reasoning_outcome.assumptions or normalized.warnings:
                analytics_result = analytics_result.model_copy(
                    update={
                        "insights": {
                            **analytics_result.insights,
                            "typed_result_schema": normalized.schema_name,
                            "typed_result_warnings": normalized.warnings,
                            "reasoning_findings": reasoning_outcome.findings,
                            "reasoning_assumptions": reasoning_outcome.assumptions,
                            "low_sample_groups": reasoning_outcome.low_sample_groups,
                            "baseline_delta": reasoning_outcome.baseline_delta,
                        }
                    }
                )

            # Internal result validation (Agent Intelligence Foundation): rule-based
            # sanity findings are logged for observability; they never block the flow.
            validation = ResultValidator().validate(
                query_result,
                plan=state.query_plan,
                sql=state.generated_sql.sql if state.generated_sql else "",
            )
            if validation.findings:
                logger.warning(
                    "Result validation findings: %s",
                    [f"{finding.check}: {finding.detail}" for finding in validation.findings],
                    extra={"result_validation": validation.model_dump()},
                )

            logger.info("AnalyzeResultsNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "query_result": query_result,
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
