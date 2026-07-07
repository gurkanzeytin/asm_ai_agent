import logging

from app.application_models.generated_sql import GeneratedSQL
from app.llm.interfaces import ILLMProvider
from app.parsers.interfaces import IOutputParser
from app.services.exceptions import SQLServiceException
from app.services.interfaces import ISQLService
from app.sql_validator.interfaces import ISQLValidator

logger = logging.getLogger(__name__)


class SQLService(ISQLService):
    """Orchestrates LLM query generation, output parsing, and safety validation."""

    def __init__(
        self,
        llm_provider: ILLMProvider,
        output_parser: IOutputParser,
        sql_validator: ISQLValidator,
    ):
        self.llm_provider = llm_provider
        self.output_parser = output_parser
        self.sql_validator = sql_validator

    async def generate_sql(self, prompt: str) -> GeneratedSQL:
        """Sends pre-rendered prompt to LLM provider, parses SQL, and verifies safety."""
        logger.info("SQLService SQL generation and validation sequence started.")
        try:
            llm_response = await self.llm_provider.generate(prompt)

            cleaned_sql = self.output_parser.parse_sql(llm_response.content)
            validation_result = self.sql_validator.validate(cleaned_sql)

            # Retrieve diagnostic details safely
            meta = self.llm_provider.get_metadata()
            provider_name = meta.get("provider", "unknown")

            logger.info(
                "SQLService SQL sequence completed successfully.",
                extra={
                    "valid": validation_result.valid,
                    "statement_type": validation_result.statement_type,
                    "latency_ms": llm_response.latency_ms,
                },
            )

            return GeneratedSQL(
                sql=cleaned_sql,
                normalized_sql=validation_result.normalized_sql,
                validation_result=validation_result,
                provider=provider_name,
                model=llm_response.model,
                latency_ms=llm_response.latency_ms,
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
            )

        except Exception as e:
            logger.error(f"SQLService failed during SQL generation sequence: {e}")
            raise SQLServiceException(f"Failed during SQL generation sequence: {e}") from e
