from datetime import datetime, timezone
import logging
from typing import Optional

from app.application_models.generated_report import GeneratedReport
from app.application_models.workflow_models import QueryResult
from app.llm.interfaces import ILLMProvider
from app.services.exceptions import ReportServiceException
from app.services.interfaces import IPromptService, IReportService
from app.services.report_generator import IReportGenerator, NarrativeReportGenerator

logger = logging.getLogger(__name__)


class ReportService(IReportService):
    """Synthesizes narrative Markdown reports using prompt and LLM providers."""

    def __init__(
        self,
        prompt_service: IPromptService,
        llm_provider: ILLMProvider,
        generator: Optional[IReportGenerator] = None,
    ):
        self.prompt_service = prompt_service
        self.llm_provider = llm_provider
        self.generator = generator or NarrativeReportGenerator()

    async def generate_report(
        self, question: str, sql: str, query_result: QueryResult, execution_id: Optional[str] = None
    ) -> GeneratedReport:
        """Loads rendering inputs, coordinates LLM invocation, and formats report outputs."""
        logger.info("ReportService report generation sequence started.")
        try:
            full_prompt = await self.prompt_service.render_report_prompt(
                question=question, sql=sql, query_result=query_result
            )

            llm_response = await self.generator.generate(full_prompt, self.llm_provider)

            # Try to extract a title header from the generated markdown text
            title = None
            for line in llm_response.content.split("\n"):
                if line.strip().startswith("#"):
                    title = line.strip("# ").strip()
                    break

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
                generated_at=datetime.now(timezone.utc),
                execution_id=execution_id,
            )

        except Exception as e:
            logger.error(f"ReportService failed during report generation sequence: {e}")
            raise ReportServiceException(f"Failed during report generation sequence: {e}") from e

