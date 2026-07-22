import logging
import time
from datetime import UTC, datetime

from app.application_models.generated_report import GeneratedReport
from app.application_models.workflow_models import QueryResult
from app.insights.models import InsightConfidence, InsightResult
from app.insights.output_validation import ENGLISH_WORD_PATTERN
from app.llm.interfaces import ILLMProvider
from app.reporting.report_classifier import ReportClassifier, ReportType
from app.reporting.template_renderer import TemplateReportRenderer
from app.services.exceptions import ReportServiceException
from app.services.interfaces import IPromptService, IReportService
from app.services.report_generator import IReportGenerator, NarrativeReportGenerator
from app.services.result_safety import cap_query_result
from app.shared.result_limits import DEFAULT_GROUPED_RESULT_LIMIT

logger = logging.getLogger(__name__)

_DEFAULT_TURKISH_TITLE = "Sorgu Sonucu"


class ReportService(IReportService):
    """Synthesizes narrative Markdown reports using prompt and LLM providers."""

    def __init__(
        self,
        prompt_service: IPromptService,
        llm_provider: ILLMProvider,
        generator: IReportGenerator | None = None,
        classifier: ReportClassifier | None = None,
        template_renderer: TemplateReportRenderer | None = None,
    ):
        self.prompt_service = prompt_service
        self.llm_provider = llm_provider
        self.generator = generator or NarrativeReportGenerator()
        self.classifier = classifier or ReportClassifier()
        self.template_renderer = template_renderer or TemplateReportRenderer()

    async def generate_report(
        self,
        question: str,
        sql: str,
        query_result: QueryResult,
        execution_id: str | None = None,
        insights: InsightResult | None = None,
    ) -> GeneratedReport:
        """Classifies results, renders templates first, and falls back to LLM analytics.

        Analytical reports reuse the Insight Engine narrative when one is available:
        the insight LLM has already produced the executive summary, highlights, and
        observations for the same analytics, so invoking a second LLM to re-derive
        them from raw rows only duplicates work.
        """
        logger.info("ReportService report generation sequence started.")
        start_time = time.perf_counter()
        try:
            query_result = self._normalize_query_result(query_result)
            report_type = self.classifier.classify(query_result, question=question, sql=sql)

            if report_type == ReportType.ANALYTICAL and self._insights_usable(insights):
                return self._render_insight_report(
                    insights, query_result, execution_id, start_time
                )
            template_result = self.template_renderer.render(report_type, query_result)
            if template_result is not None:
                latency_ms = (time.perf_counter() - start_time) * 1000
                self._log_report_telemetry(
                    report_type=report_type,
                    renderer="Template",
                    template_name=template_result.template_name,
                    latency_ms=latency_ms,
                    llm_invoked=False,
                )
                return GeneratedReport(
                    title=template_result.title,
                    summary=None,
                    markdown=template_result.markdown,
                    insights=None,
                    recommendations=None,
                    tables=None,
                    charts=None,
                    provider="template",
                    model=template_result.template_name,
                    latency_ms=latency_ms,
                    prompt_tokens=None,
                    completion_tokens=None,
                    generated_at=datetime.now(UTC),
                    execution_id=execution_id,
                )

            full_prompt = await self.prompt_service.render_report_prompt(
                question=question, sql=sql, query_result=query_result
            )

            try:
                llm_response = await self.generator.generate(full_prompt, self.llm_provider)
            except Exception as llm_error:
                # The report is the last user-facing stage: an LLM failure (timeout,
                # connection, parsing) must degrade to a deterministic template, never
                # surface as a generic workflow error.
                logger.warning(
                    f"Report LLM generation failed; falling back to template table: {llm_error}"
                )
                return self._render_fallback_report(
                    report_type, query_result, execution_id, start_time
                )

            # Try to extract a title header from the generated markdown text
            title = None
            for line in llm_response.content.split("\n"):
                if line.strip().startswith("#"):
                    title = line.strip("# ").strip()
                    break
            # Safety net: no title-scraped heading, or the LLM ignored the
            # Turkish-only directive — never surface a missing/English title.
            if not title or ENGLISH_WORD_PATTERN.search(title):
                title = _DEFAULT_TURKISH_TITLE

            logger.info(
                "ReportService LLM call completed: latency_ms=%.1f completion_tokens=%s",
                llm_response.latency_ms,
                llm_response.completion_tokens,
            )
            logger.info(
                "ReportService report sequence completed successfully.",
                extra={
                    "model": llm_response.model,
                    "latency_ms": llm_response.latency_ms,
                    "report_length": len(llm_response.content),
                },
            )

            meta = self.llm_provider.get_metadata()
            provider_name = "unknown"
            if isinstance(meta, dict):
                provider_name = meta.get("provider", "unknown")

            self._log_report_telemetry(
                report_type=report_type,
                renderer=provider_name,
                template_name=None,
                latency_ms=llm_response.latency_ms,
                llm_invoked=True,
            )

            return GeneratedReport(
                title=title,
                summary=None,
                markdown=llm_response.content,
                insights=None,
                recommendations=None,
                tables=None,
                charts=None,
                provider=provider_name,
                model=llm_response.model,
                latency_ms=llm_response.latency_ms,
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
                generated_at=datetime.now(UTC),
                execution_id=execution_id,
            )

        except Exception as e:
            logger.error(f"ReportService failed during report generation sequence: {e}")
            raise ReportServiceException(f"Failed during report generation sequence: {e}") from e

    def _insights_usable(self, insights: InsightResult | None) -> bool:
        """An insight narrative can replace the report LLM only when it carries evidence."""
        return (
            insights is not None
            and insights.confidence != InsightConfidence.LOW
            and bool(insights.summary)
        )

    def _render_insight_report(
        self,
        insights: InsightResult,
        query_result: QueryResult,
        execution_id: str | None,
        start_time: float,
    ) -> GeneratedReport:
        """Assembles the analytical report from the existing insight narrative + data table."""
        from app.core.config import settings

        max_rows = min(
            getattr(settings, "REPORT_MAX_ROWS", DEFAULT_GROUPED_RESULT_LIMIT),
            DEFAULT_GROUPED_RESULT_LIMIT,
        )
        capped = cap_query_result(query_result, max_rows)
        table_result = self.template_renderer.render(ReportType.TABLE, capped)

        # Section names per spec: Sorgu Sonucu (title+summary) / Öne Çıkan
        # Bulgular (highlights+observations merged) / Olası Açıklamalar
        # (considerations — the LLM's hypotheses, framed as such by the
        # insight_generation.md prompt directive). Deterministic assumptions
        # and limitations (partial-period/comparison-sufficiency) live in a
        # separate "Varsayımlar ve Sınırlamalar" section appended later by
        # GenerateReportNode._append_reasoning_sections, sourced from
        # analytics directly rather than the LLM.
        lines: list[str] = [f"# {insights.title}", ""]
        lines += ["## Sorgu Sonucu", insights.summary, ""]
        findings = list(insights.highlights) + list(insights.observations)
        if findings:
            lines.append("## Öne Çıkan Bulgular")
            lines += [f"- {item}" for item in findings]
            lines.append("")
        if insights.considerations:
            lines.append("## Olası Açıklamalar")
            lines += [f"- {item}" for item in insights.considerations]
            lines.append("")
        if table_result is not None:
            lines.append("## Veri")
            table_body = table_result.markdown.split("\n", 2)[-1].lstrip("\n")
            lines.append(table_body)

        latency_ms = (time.perf_counter() - start_time) * 1000
        self._log_report_telemetry(
            report_type=ReportType.ANALYTICAL,
            renderer="InsightReuse",
            template_name="insight_narrative",
            latency_ms=latency_ms,
            llm_invoked=False,
        )
        return GeneratedReport(
            title=insights.title,
            summary=insights.summary,
            markdown="\n".join(lines).strip(),
            insights=None,
            recommendations=None,
            tables=None,
            charts=None,
            provider="insight_reuse",
            model=insights.model,
            latency_ms=latency_ms,
            prompt_tokens=None,
            completion_tokens=None,
            generated_at=datetime.now(UTC),
            execution_id=execution_id,
        )

    def _render_fallback_report(
        self,
        report_type: ReportType,
        query_result: QueryResult,
        execution_id: str | None,
        start_time: float,
    ) -> GeneratedReport:
        """Renders a deterministic table report when the LLM path fails.

        Rows are capped to REPORT_MAX_ROWS so an unaggregated result cannot
        produce an unbounded markdown table.
        """
        from app.core.config import settings

        max_rows = min(
            getattr(settings, "REPORT_MAX_ROWS", DEFAULT_GROUPED_RESULT_LIMIT),
            DEFAULT_GROUPED_RESULT_LIMIT,
        )
        capped = cap_query_result(query_result, max_rows)

        template_result = self.template_renderer.render(ReportType.TABLE, capped)
        latency_ms = (time.perf_counter() - start_time) * 1000
        self._log_report_telemetry(
            report_type=report_type,
            renderer="TemplateFallback",
            template_name=template_result.template_name if template_result else "table",
            latency_ms=latency_ms,
            llm_invoked=True,
        )
        return GeneratedReport(
            title=template_result.title if template_result else "Sorgu Sonucu",
            summary=None,
            markdown=template_result.markdown if template_result else "",
            insights=None,
            recommendations=None,
            tables=None,
            charts=None,
            provider="template",
            model="fallback_table",
            latency_ms=latency_ms,
            prompt_tokens=None,
            completion_tokens=None,
            generated_at=datetime.now(UTC),
            execution_id=execution_id,
        )

    def _normalize_query_result(self, query_result: QueryResult | list[dict]) -> QueryResult:
        if isinstance(query_result, QueryResult):
            return query_result

        if isinstance(query_result, list):
            columns = list(query_result[0].keys()) if query_result else []
            return QueryResult(
                columns=columns,
                rows=query_result,
                row_count=len(query_result),
                execution_time_ms=0.0,
                success=True,
                executed_at=datetime.now(UTC),
                database_provider="mssql",
            )

        raise TypeError("query_result must be a QueryResult or list of row dictionaries.")

    def _log_report_telemetry(
        self,
        *,
        report_type: ReportType,
        renderer: str,
        template_name: str | None,
        latency_ms: float,
        llm_invoked: bool,
    ) -> None:
        logger.info(
            "\n================ REPORT ================\n"
            f"Type: {report_type.name}\n"
            f"Renderer: {renderer}\n"
            f"Template: {template_name or 'none'}\n"
            f"LLM Invoked: {llm_invoked}\n"
            f"Latency: {latency_ms:.1f} ms\n"
            "========================================",
            extra={
                "report_type": report_type.value,
                "renderer": renderer,
                "template": template_name,
                "latency_ms": latency_ms,
                "llm_invoked": llm_invoked,
            },
        )
