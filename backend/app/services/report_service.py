import logging

from app.application_models.generated_report import GeneratedReport
from app.llm.interfaces import ILLMProvider
from app.services.exceptions import ReportServiceException
from app.services.interfaces import IPromptService, IReportService

logger = logging.getLogger(__name__)


class ReportService(IReportService):
    """Synthesizes narrative Markdown reports using prompt and LLM providers."""

    def __init__(self, prompt_service: IPromptService, llm_provider: ILLMProvider):
        self.prompt_service = prompt_service
        self.llm_provider = llm_provider

    async def generate_report(self, question: str, sql: str, query_result: list) -> GeneratedReport:
        """Loads rendering inputs, coordinates LLM invocation, and formats report outputs."""
        logger.info("ReportService report generation sequence started.")
        try:
            full_prompt = await self.prompt_service.render_report_prompt(
                question=question, sql=sql, query_result=query_result
            )

            llm_response = await self.llm_provider.generate(full_prompt)

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

            return GeneratedReport(
                title=title,
                summary=None,
                markdown=llm_response.content,
                tables=None,
                charts=None,
            )

        except Exception as e:
            logger.error(f"ReportService failed during report generation sequence: {e}")
            raise ReportServiceException(f"Failed during report generation sequence: {e}") from e
