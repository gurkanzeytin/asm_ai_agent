import logging

import sqlglot
import sqlglot.expressions as exp

from app.application_models.generated_sql import GeneratedSQL
from app.core.config import settings
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
        """Sends pre-rendered prompt to LLM provider, parses SQL, and verifies safety.

        Uses think=False and num_predict=200 for fast completion and output size control.
        Executes exactly one repair attempt if the output is invalid SQL or unsafe.
        """
        logger.info("SQLService SQL generation and validation sequence started.")
        try:
            # 1. First Attempt
            llm_response = await self.llm_provider.generate(
                prompt,
                think=False,
                options={"num_predict": 200},
            )

            # Log raw output immediately in debug mode
            if settings.DEBUG:
                logger.info(
                    "\n================================================\n"
                    "RAW LLM SQL OUTPUT\n\n"
                    "%s\n"
                    "================================================",
                    llm_response.content,
                )

            cleaned_sql = self._remove_redundant_identifier_projection(
                self.output_parser.parse_sql(llm_response.content)
            )
            
            # Check if it starts with SELECT or WITH (case-insensitive)
            upper_sql = cleaned_sql.upper().strip()
            is_sql = upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")
            
            validation_result = None
            if is_sql:
                validation_result = self.sql_validator.validate(cleaned_sql)

            # Determine if a repair is needed
            repair_attempt_used = False
            first_attempt_failed = (
                not is_sql
                or not validation_result
                or not validation_result.valid
            )

            if first_attempt_failed:
                repair_attempt_used = True
                raw_preview = llm_response.content[:300]
                logger.warning(
                    f"First SQL generation attempt failed safety or formatting checks.\n"
                    f"  - Bounded raw output preview: {raw_preview!r}\n"
                    f"  - Validation Result: {validation_result.valid if validation_result else False}\n"
                    "Executing single repair attempt."
                )

                # Build repair prompt combining original prompt, failed response, and correction
                repair_instruction = (
                    "The previous response was not valid SQL. "
                    "Generate ONE executable SQL statement only. "
                    "Do not explain. "
                    "Return only SQL."
                )
                repair_prompt = (
                    f"{prompt}\n\n"
                    f"--- Previous response ---\n"
                    f"{llm_response.content}\n\n"
                    f"{repair_instruction}"
                )

                # Retry LLM generation
                llm_response = await self.llm_provider.generate(
                    repair_prompt,
                    think=False,
                    options={"num_predict": 200},
                )

                if settings.DEBUG:
                    logger.info(
                        "\n================================================\n"
                        "RAW LLM SQL REPAIR OUTPUT\n\n"
                        "%s\n"
                        "================================================",
                        llm_response.content,
                    )

                cleaned_sql = self._remove_redundant_identifier_projection(
                    self.output_parser.parse_sql(llm_response.content)
                )
                upper_sql = cleaned_sql.upper().strip()
                is_sql = upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")
                
                if is_sql:
                    validation_result = self.sql_validator.validate(cleaned_sql)
                else:
                    validation_result = None

            # 2. Final check before completing flow:
            # If no SQL statement starting with SELECT/WITH can be extracted, fail immediately
            if not is_sql:
                raw_preview = llm_response.content[:300]
                logger.error(
                    f"SQL generation failed: Output does not start with SELECT or WITH.\n"
                    f"  - Bounded raw output preview: {raw_preview!r}"
                )
                raise SQLServiceException("Failed to generate a valid SQL query: output does not start with SELECT or WITH.")

            # Safety check validation
            assert validation_result is not None

            # Log parsed SQL properties (first 300 chars preview)
            line_count = len(cleaned_sql.splitlines())
            ends_with_semicolon = cleaned_sql.strip().endswith(";")
            sql_preview = cleaned_sql[:300]
            logger.info(
                "SQLService parsed SQL properties:\n"
                f"  - Extracted SQL Length: {len(cleaned_sql)}\n"
                f"  - Line Count: {line_count}\n"
                f"  - Ends with Semicolon: {ends_with_semicolon}\n"
                f"  - Parsed SQL Preview (first 300 chars): {sql_preview!r}"
            )

            if not validation_result.valid:
                raw_preview = llm_response.content[:300]
                logger.warning(
                    f"SQL validation safety check failed.\n"
                    f"  - Validation errors/reason: {getattr(validation_result, 'reason', None)}\n"
                    f"  - Bounded raw output preview: {raw_preview!r}"
                )

            # Log metrics in development mode
            if settings.DEBUG:
                logger.info(
                    "SQL generation debug metrics: "
                    "prompt_tokens=%s "
                    "completion_tokens=%s "
                    "raw_output_length=%d "
                    "extracted_sql_length=%d "
                    "parser_strategy=%s "
                    "repair_attempt_used=%s",
                    str(llm_response.prompt_tokens),
                    str(llm_response.completion_tokens),
                    len(llm_response.content),
                    len(cleaned_sql),
                    "regex_extraction",
                    str(repair_attempt_used),
                )

            # Retrieve diagnostic details safely
            meta = self.llm_provider.get_metadata()
            provider_name = meta.get("provider", "unknown")

            logger.info(
                "SQLService LLM call completed: latency_ms=%.1f completion_tokens=%s",
                llm_response.latency_ms,
                llm_response.completion_tokens,
            )
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

        except SQLServiceException:
            # Re-raise explicit service exceptions directly
            raise
        except Exception as e:
            logger.error(f"SQLService failed during SQL generation sequence: {e}")
            raise SQLServiceException(f"Failed during SQL generation sequence: {e}") from e

    def _remove_redundant_identifier_projection(self, sql: str) -> str:
        try:
            expression = sqlglot.parse_one(sql, read=getattr(settings, "SQL_DIALECT", "sqlite"))
        except Exception:
            return sql

        select = expression if isinstance(expression, exp.Select) else expression.find(exp.Select)
        if not select:
            return sql

        projections = list(select.expressions)
        if len(projections) < 3:
            return sql

        has_aggregate = any(_is_aggregate_projection(projection) for projection in projections)
        has_descriptive = any(_is_descriptive_projection(projection) for projection in projections)
        if not has_aggregate or not has_descriptive:
            return sql

        filtered = [
            projection
            for projection in projections
            if not _is_identifier_projection(projection)
        ]
        if len(filtered) == len(projections) or len(filtered) < 2:
            return sql

        select.set("expressions", filtered)
        normalized = expression.sql(dialect=getattr(settings, "SQL_DIALECT", "sqlite"), pretty=False)
        return normalized if normalized.endswith(";") else f"{normalized};"


def _projection_name(projection: exp.Expression) -> str:
    return (projection.alias_or_name or "").lower()


def _is_aggregate_projection(projection: exp.Expression) -> bool:
    upper_sql = projection.sql().upper()
    return any(function in upper_sql for function in ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX("))


def _is_descriptive_projection(projection: exp.Expression) -> bool:
    name = _projection_name(projection)
    sql = projection.sql().lower()
    markers = ("ad_soyad", "bolum_adi", "sirket_adi", "test_adi", "name", "title", "unvan")
    return any(marker in name or marker in sql for marker in markers) or name.endswith("_adi")


def _is_identifier_projection(projection: exp.Expression) -> bool:
    name = _projection_name(projection)
    if name == "id" or name.endswith("_id"):
        return True
    if isinstance(projection, exp.Column):
        column_name = projection.name.lower()
        return column_name == "id" or column_name.endswith("_id")
    if isinstance(projection, exp.Alias) and isinstance(projection.this, exp.Column):
        column_name = projection.this.name.lower()
        return column_name == "id" or column_name.endswith("_id")
    return False
