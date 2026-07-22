import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.services.interfaces import IWorkflowService

logger = logging.getLogger(__name__)


class GenerateReportNode(IAgentNode):
    """Workflow node responsible for generating analytical narrative reports from query execution results."""

    def __init__(self, workflow_service: IWorkflowService):
        self.workflow_service = workflow_service

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateReportNode execution started.")
        start_time = time.perf_counter()

        # If errors already present, skip execution defensively
        if state.errors:
            logger.warning("GenerateReportNode skipped: errors are present on incoming state.")
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "current_node": "generate_report",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_report": duration},
                }
            )

        # Item 14 (failure behavior): an invalid result shape must never be
        # narrated as if it were a real answer — no fabricated insight, no
        # LLM report call, and the workflow must not resolve as a success.
        if state.analytics_blocked_reason:
            logger.warning(
                "GenerateReportNode: analytics blocked (%s); returning a safe "
                "clarification instead of a fabricated report.",
                state.analytics_blocked_reason,
            )
            duration = (time.perf_counter() - start_time) * 1000
            report_dto = GeneratedReport(
                title="Sonuç doğrulanamadı",
                summary=(
                    "Sorgu çalıştı ancak sonuç, planlanan analiz ile eşleşmedi; "
                    "bu nedenle güvenilir bir yorum üretilemedi."
                ),
                markdown=(
                    "## Sonuç doğrulanamadı\n\n"
                    "Sorgu çalıştı ancak dönen sonucun yapısı planlanan analizle "
                    "eşleşmedi, bu yüzden bir yorum üretilmedi. Lütfen soruyu "
                    "daraltarak veya farklı bir şekilde ifade ederek tekrar deneyin."
                ),
                provider="deterministic",
                model="none",
            )
            return state.model_copy(
                update={
                    "generated_report": report_dto,
                    "outcome": AgentOutcome.SAFE_ERROR.value,
                    "current_node": "generate_report",
                    "completed_nodes": state.completed_nodes + ["generate_report"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_report": duration},
                }
            )

        if not state.query_result:
            logger.error("GenerateReportNode failed: query_result is missing in state.")
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "errors": state.errors + ["GenerateReportNode failed: SQL query result is missing."],
                    "current_node": "generate_report",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_report": duration},
                }
            )

        if not state.generated_sql or not state.generated_sql.sql:
            logger.error("GenerateReportNode failed: generated_sql is missing in state.")
            duration = (time.perf_counter() - start_time) * 1000
            return state.model_copy(
                update={
                    "errors": state.errors + ["GenerateReportNode failed: Generated SQL statement is missing."],
                    "current_node": "generate_report",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_report": duration},
                }
            )

        try:
            report_dto = await self.workflow_service.execute_report_generation(
                question=state.question,
                sql=state.generated_sql.sql,
                query_result=state.query_result,
                execution_id=state.workflow_id,
                # Analytical reports reuse the insight narrative instead of a second LLM call.
                insights=state.insights,
            )

            report_dto = self._append_reasoning_sections(report_dto, state)

            logger.info("GenerateReportNode execution completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            # AG-022 outcome resolution: empty result sets resolve as guided
            # NO_RESULT_GUIDANCE; a rewrite-retry success keeps REWRITE_AND_RETRY.
            if state.query_result.row_count == 0:
                outcome = AgentOutcome.NO_RESULT_GUIDANCE.value
            else:
                outcome = state.outcome or AgentOutcome.EXECUTE_SQL.value

            return state.model_copy(
                update={
                    "generated_report": report_dto,
                    "outcome": outcome,
                    "current_node": "generate_report",
                    "completed_nodes": state.completed_nodes + ["generate_report"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_report": duration},
                }
            )
        except Exception as e:
            logger.error(f"GenerateReportNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"GenerateReportNode failed: {e}"],
                    "current_node": "generate_report",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_report": duration},
                }
            )

    def _append_reasoning_sections(self, report_dto, state: AgentState):
        """Appends stated assumptions and key findings to the report markdown.

        AI-INTELLIGENCE-008: every default the planner assumed ('bu aralar' =
        son 30 gün, ...) must be visible in the answer; reasoning findings turn
        a row dump into an analytical summary. Failures degrade silently.
        """
        try:
            sections: list[str] = []
            insights = state.analytics.insights if state.analytics else {}
            findings = insights.get("reasoning_findings") or []
            metric_summaries = state.analytics.metric_summaries if state.analytics else {}
            if metric_summaries:
                # Multi-metric requests must show every requested metric, never
                # just the one the legacy single-column heuristic picked.
                metric_lines = []
                for metric_id, summary in metric_summaries.items():
                    parts = []
                    if summary.total is not None:
                        parts.append(f"toplam {summary.total:g}")
                    if summary.average is not None:
                        parts.append(f"ortalama {summary.average:g}")
                    if summary.top_dimension:
                        parts.append(f"en yüksek: {summary.top_dimension}")
                    if summary.bottom_dimension:
                        parts.append(f"en düşük: {summary.bottom_dimension}")
                    metric_lines.append(f"- **{metric_id}**: {', '.join(parts)}")
                sections.append(
                    "\n\n**Sorgulanan metrikler**\n" + "\n".join(metric_lines)
                )
            if findings:
                sections.append(
                    "\n\n**Öne çıkan bulgular**\n"
                    + "\n".join(f"- {finding}" for finding in findings)
                )
            assumptions = list((state.query_plan.assumptions if state.query_plan else None) or [])
            analytics = state.analytics
            if analytics is not None:
                # Deterministic limitations, sourced from analytics directly
                # (never the LLM) so this section stays reliable regardless of
                # routing mode.
                comparison_insufficient = analytics.comparison_sufficient is False
                if comparison_insufficient and analytics.comparison_limitation_reason:
                    assumptions.append(analytics.comparison_limitation_reason)
                trend_metrics = analytics.trend_metrics
                if trend_metrics is not None and trend_metrics.comparison_excluded_partial_period:
                    excluded = ", ".join(trend_metrics.excluded_periods)
                    assumptions.append(
                        f"{excluded} dönemi henüz tamamlanmadığı için eğilim hesabında tam "
                        "dönemlerle birlikte değerlendirilmemiştir."
                    )
            if assumptions:
                sections.append(
                    "\n\n**Varsayımlar ve Sınırlamalar**\n"
                    + "\n".join(f"- {assumption}" for assumption in assumptions)
                )
            if not sections:
                return report_dto
            return report_dto.model_copy(
                update={"markdown": report_dto.markdown + "".join(sections)}
            )
        except Exception as error:
            logger.error("Reasoning sections skipped: %s", error)
            return report_dto
