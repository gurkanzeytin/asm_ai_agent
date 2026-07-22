import logging
import re

import sqlglot
import sqlglot.expressions as exp

from app.application_models.generated_sql import GeneratedSQL
from app.core.config import settings
from app.database_intelligence.models import DatabaseContext
from app.llm.interfaces import ILLMProvider
from app.parsers.interfaces import IOutputParser
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan
from app.services.deterministic_sql_builder import DeterministicSQLBuilder, DeterministicSQL, UnsupportedPlan
from app.services.exceptions import SQLServiceException
from app.services.interfaces import ISQLService
from app.sql_validator.interfaces import ISQLValidator

logger = logging.getLogger(__name__)

# One-to-one Turkish diacritic fold used to keep string literals aligned with the
# normalized (ASCII) vocabulary of the question.
_TURKISH_FOLD_TABLE = str.maketrans(
    {
        "ı": "i",
        "İ": "I",
        "ğ": "g",
        "Ğ": "G",
        "ş": "s",
        "Ş": "S",
        "ç": "c",
        "Ç": "C",
        "ö": "o",
        "Ö": "O",
        "ü": "u",
        "Ü": "U",
    }
)


class SQLService(ISQLService):
    """Orchestrates LLM query generation, output parsing, and safety validation."""

    def __init__(
        self,
        llm_provider: ILLMProvider,
        output_parser: IOutputParser,
        sql_validator: ISQLValidator,
        compliance_validator: PlanComplianceValidator | None = None,
        deterministic_builder: DeterministicSQLBuilder | None = None,
    ):
        self.llm_provider = llm_provider
        self.output_parser = output_parser
        self.sql_validator = sql_validator
        self.compliance_validator = compliance_validator or PlanComplianceValidator()
        self.deterministic_builder = deterministic_builder or DeterministicSQLBuilder()

    async def generate_sql(
        self,
        prompt: str,
        question: str | None = None,
        database_context: DatabaseContext | None = None,
        query_plan: QueryPlan | None = None,
    ) -> GeneratedSQL:
        """Sends pre-rendered prompt to LLM provider, parses SQL, and verifies safety.

        Uses think=False and num_predict=200 for fast completion and output size control.
        Executes exactly one repair attempt if the output is invalid SQL, unsafe, or
        references identifiers absent from the retrieved schema context. String literals
        are canonicalized against the normalized question vocabulary so the LLM cannot
        re-introduce Turkish diacritics into filter values.
        """
        logger.info("SQLService SQL generation and validation sequence started.")
        try:
            deterministic, repair_reason, missing_metrics_before = self._try_deterministic(
                query_plan, database_context, prompt
            )
            if deterministic is not None:
                return deterministic

            # 1. First Attempt. 400 tokens: monthly-aggregation queries legitimately
            # exceed 200 and truncation yields corrupt identifiers (e.g. 'test_son').
            llm_response = await self.llm_provider.generate(
                prompt,
                think=False,
                options={"num_predict": 400},
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

            cleaned_sql, is_sql, validation_result, schema_issues = self._parse_and_validate(
                llm_response.content, question, database_context
            )
            trend_issue = self._trend_aggregation_issue(question, cleaned_sql) if is_sql else None
            truncated = llm_response.finish_reason == "max_tokens"
            compliance_missing = self._compliance_missing(
                cleaned_sql, query_plan, is_sql, validation_result, schema_issues
            )

            # Determine if a repair is needed
            repair_attempt_used = False
            first_attempt_failed = (
                not is_sql
                or not validation_result
                or not validation_result.valid
                or bool(schema_issues)
                or bool(trend_issue)
                or truncated
                or bool(compliance_missing)
            )

            if first_attempt_failed:
                repair_attempt_used = True
                raw_preview = llm_response.content[:300]
                logger.warning(
                    f"First SQL generation attempt failed safety, formatting, or schema checks.\n"
                    f"  - Bounded raw output preview: {raw_preview!r}\n"
                    f"  - Validation Result: {validation_result.valid if validation_result else False}\n"
                    f"  - Schema identifier issues: {schema_issues or 'none'}\n"
                    f"  - Trend aggregation issue: {trend_issue or 'none'}\n"
                    f"  - Plan compliance missing: {compliance_missing or 'none'}\n"
                    f"  - Truncated (max_tokens): {truncated}\n"
                    "Executing single repair attempt."
                )

                # Build repair prompt combining original prompt, failed response, and correction
                if truncated:
                    repair_instruction = (
                        "The previous response was cut off before completion. "
                        "Generate ONE complete but SIMPLE SQL statement: a single SELECT "
                        "with only the columns and JOINs strictly needed to answer the "
                        "question. Do not explain. Return only SQL."
                    )
                elif trend_issue and is_sql and validation_result and validation_result.valid and not schema_issues:
                    repair_instruction = (
                        "The question asks for an analysis/trend over a time period, but the "
                        "previous SQL returns raw rows without time aggregation. Rewrite it as "
                        "a monthly aggregation: SELECT strftime('%Y-%m', <date column>) AS ay, "
                        "COUNT(*) AS adet FROM <table> WHERE <date filter> "
                        "GROUP BY ay ORDER BY ay. "
                        "Use only the tables and columns listed in the Schema section. "
                        "Generate ONE executable SQL statement only. "
                        "Do not explain. Return only SQL."
                    )
                elif schema_issues:
                    repair_instruction = (
                        "The previous SQL references identifiers that do not exist in the "
                        f"schema: {'; '.join(schema_issues)}. "
                        "Rewrite the SQL using ONLY the tables and columns listed in the "
                        "Schema section, spelled exactly as listed. "
                        "Generate ONE executable SQL statement only. "
                        "Do not explain. Return only SQL."
                    )
                elif compliance_missing:
                    repair_instruction = (
                        "The previous SQL does not implement all planned constraints. "
                        f"Missing: {'; '.join(compliance_missing)}. "
                        "Rewrite the SQL implementing EVERY item listed in the Plan "
                        "section, without dropping any existing filter. "
                        "Generate ONE executable SQL statement only. "
                        "Do not explain. Return only SQL."
                    )
                else:
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
                    options={"num_predict": 400},
                )

                if settings.DEBUG:
                    logger.info(
                        "\n================================================\n"
                        "RAW LLM SQL REPAIR OUTPUT\n\n"
                        "%s\n"
                        "================================================",
                        llm_response.content,
                    )

                cleaned_sql, is_sql, validation_result, schema_issues = self._parse_and_validate(
                    llm_response.content, question, database_context
                )
                # Post-repair compliance status is logged for observability; a
                # still-missing constraint never blocks an otherwise valid SQL.
                compliance_missing = self._compliance_missing(
                    cleaned_sql, query_plan, is_sql, validation_result, schema_issues
                )
                if compliance_missing:
                    logger.warning(
                        "Plan compliance still incomplete after repair attempt: %s",
                        "; ".join(compliance_missing),
                        extra={"missing_constraints": compliance_missing},
                    )

            # 2. Final check before completing flow:
            # If no SQL statement starting with SELECT/WITH can be extracted, fail immediately
            if not is_sql:
                raw_preview = llm_response.content[:300]
                logger.error(
                    f"SQL generation failed: Output does not start with SELECT or WITH.\n"
                    f"  - Bounded raw output preview: {raw_preview!r}"
                )
                raise SQLServiceException("Failed to generate a valid SQL query: output does not start with SELECT or WITH.")

            # Schema identifier check: never let SQL with unknown identifiers reach execution
            if schema_issues:
                logger.error(
                    "SQL generation failed: query references identifiers outside the "
                    f"retrieved schema context after repair: {'; '.join(schema_issues)}"
                )
                raise SQLServiceException(
                    "Failed to generate a valid SQL query: unknown schema identifiers "
                    f"({'; '.join(schema_issues)})."
                )

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

            missing_metrics_after = (
                self.compliance_validator.check(cleaned_sql, query_plan).missing_metrics
                if query_plan is not None
                else []
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
                sql_source="repaired_llm" if repair_attempt_used else "llm",
                repair_attempted=repair_reason is not None,
                repair_reason=repair_reason,
                missing_metrics_before=missing_metrics_before,
                missing_metrics_after=missing_metrics_after,
            )

        except SQLServiceException:
            # Re-raise explicit service exceptions directly
            raise
        except Exception as e:
            logger.error(f"SQLService failed during SQL generation sequence: {e}")
            raise SQLServiceException(f"Failed during SQL generation sequence: {e}") from e

    def _try_deterministic(
        self,
        query_plan: QueryPlan | None,
        database_context: DatabaseContext | None,
        prompt: str,
    ) -> tuple[GeneratedSQL | None, str | None, list[str]]:
        """Returns (generated_sql_or_none, repair_reason, missing_metrics_before).

        `repair_reason`/`missing_metrics_before` are only ever populated when
        this method falls through to the LLM path because of a genuine
        multi-metric coverage gap in the deterministic builder output — the
        single bounded repair signal this layer produces. No LLM call happens
        here and no loop is introduced; the caller's existing (already
        bounded, single-repair) LLM path takes over exactly as it does for
        any other `UnsupportedPlan`.
        """
        if query_plan is None:
            return None, None, []
        adaptive_retry = "ADAPTIVE_EMPTY_RESULT" in prompt
        built = self.deterministic_builder.build(query_plan, adaptive_retry=adaptive_retry)
        if isinstance(built, UnsupportedPlan):
            logger.info("Deterministic SQL builder unsupported: %s", built.reason)
            return None, None, []

        cleaned_sql, is_sql, validation_result, schema_issues = self._parse_and_validate(
            built.sql, query_plan.question, database_context
        )
        if not is_sql or not validation_result or not validation_result.valid:
            reason = getattr(validation_result, "reason", None) if validation_result else "not SQL"
            raise SQLServiceException(
                f"Deterministic SQL builder produced invalid SQL: {reason}"
            )
        if schema_issues:
            raise SQLServiceException(
                "Deterministic SQL builder produced SQL with unknown schema identifiers "
                f"({'; '.join(schema_issues)})."
            )

        compliance = self.compliance_validator.check(
            cleaned_sql,
            query_plan,
            expected_aliases=built.expected_aliases,
            deterministic=True,
        )
        if not compliance.compliant:
            if compliance.missing_metrics and not compliance.missing:
                # A genuine deterministic-builder metric-coverage gap (e.g. an
                # unverified metric mapping). No retry of the same deterministic
                # path — it would reproduce the same gap — fall through once to
                # the existing LLM path.
                reason = (
                    "deterministic_metric_alias_gap: "
                    f"{', '.join(compliance.missing_metrics)}"
                )
                logger.warning(
                    "Deterministic SQL missing metric coverage; falling through "
                    "to LLM path: %s",
                    compliance.missing_metrics,
                    extra={"missing_metrics": compliance.missing_metrics},
                )
                return None, reason, compliance.missing_metrics
            raise SQLServiceException(
                "Deterministic SQL builder failed plan compliance: "
                f"{'; '.join(compliance.missing)}"
            )

        meta = self.llm_provider.get_metadata()
        return (
            GeneratedSQL(
                sql=cleaned_sql,
                normalized_sql=validation_result.normalized_sql,
                validation_result=validation_result,
                provider=meta.get("provider", "deterministic"),
                model="deterministic-query-plan-builder",
                latency_ms=0.0,
                prompt_tokens=0,
                completion_tokens=0,
                sql_source="deterministic",
                result_schema=built.result_schema,
                expected_aliases=built.expected_aliases,
                metric_aliases=built.metric_aliases,
            ),
            None,
            [],
        )

    def _compliance_missing(
        self,
        sql: str,
        query_plan: QueryPlan | None,
        is_sql: bool,
        validation_result: object | None,
        schema_issues: list[str],
    ) -> list[str]:
        """Runs the plan compliance check when the SQL is otherwise well-formed.

        Skipped when the SQL already failed structural/safety/schema checks —
        those failures drive their own, more specific repair instructions.
        """
        if (
            query_plan is None
            or not is_sql
            or not validation_result
            or not getattr(validation_result, "valid", False)
            or schema_issues
        ):
            return []
        try:
            return self.compliance_validator.check(sql, query_plan).missing
        except Exception as error:  # compliance must never break generation
            logger.error(f"Plan compliance check failed open: {error}")
            return []

    def _parse_and_validate(
        self,
        raw_content: str,
        question: str | None,
        database_context: DatabaseContext | None,
    ) -> tuple[str, bool, object | None, list[str]]:
        """Extracts, cleans, canonicalizes, and validates SQL from raw LLM output."""
        cleaned_sql = self._remove_redundant_identifier_projection(
            self.output_parser.parse_sql(raw_content)
        )
        cleaned_sql = self._canonicalize_string_literals(cleaned_sql, question)

        upper_sql = cleaned_sql.upper().strip()
        is_sql = upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")

        validation_result = None
        schema_issues: list[str] = []
        if is_sql:
            validation_result = self.sql_validator.validate(cleaned_sql)
            if validation_result.valid and database_context is not None:
                schema_issues = self.sql_validator.validate_schema_identifiers(
                    cleaned_sql, database_context
                )
        return cleaned_sql, is_sql, validation_result, schema_issues

    def _trend_aggregation_issue(self, question: str | None, sql: str) -> str | None:
        """Detects trend/analysis questions whose SQL lacks time-bucketed aggregation.

        The question arrives with relative dates already resolved to explicit ISO
        ranges ("... tarihleri arasinda ..."), so a period-analysis question is one
        that contains an analysis marker AND a date range. Such questions must
        aggregate (GROUP BY a time bucket), never dump raw rows: unaggregated
        results produce meaningless analytics and oversized report prompts.
        """
        if not question:
            return None
        folded = question.translate(_TURKISH_FOLD_TABLE).lower()
        has_analysis_marker = bool(re.search(r"\b(analiz|trend|egilim)\w*", folded))
        has_date_range = bool(
            re.search(r"tarihleri arasinda|\d{4}-\d{2}-\d{2}", folded)
        )
        if not (has_analysis_marker and has_date_range):
            return None
        if re.search(r"\bgroup\s+by\b", sql, re.IGNORECASE):
            return None
        return "period-analysis question without GROUP BY time aggregation"

    def _canonicalize_string_literals(self, sql: str, question: str | None) -> str:
        """Restores normalized-question vocabulary inside generated string literals.

        The question arrives ASCII-normalized (canonical database vocabulary), but the
        LLM tends to 'correct' filter values back to proper Turkish spelling
        ('Çocuk Sağlığı' instead of the stored 'Cocuk Sagligi'). Any string literal
        whose diacritic-folded form appears in the folded question is rewritten to
        that folded form. Case differences are handled by the SQL Server database
        collation (case-insensitive by default), so no COLLATE clause is added.
        """
        if not question:
            return sql
        dialect = getattr(settings, "SQL_DIALECT", "tsql")
        try:
            expression = sqlglot.parse_one(sql, read=dialect)
        except Exception:
            return sql
        if expression is None:
            return sql

        folded_question = question.translate(_TURKISH_FOLD_TABLE).lower()
        changed = False
        for literal in list(expression.find_all(exp.Literal)):
            if not literal.is_string:
                continue
            value = literal.this
            folded_value = value.translate(_TURKISH_FOLD_TABLE)
            if folded_value.lower() not in folded_question:
                continue
            if folded_value != value:
                literal.set("this", folded_value)
                changed = True
        if not changed:
            return sql

        normalized = expression.sql(dialect=getattr(settings, "SQL_DIALECT", "tsql"), pretty=False)
        return normalized if normalized.endswith(";") else f"{normalized};"

    def _remove_redundant_identifier_projection(self, sql: str) -> str:
        try:
            expression = sqlglot.parse_one(sql, read=getattr(settings, "SQL_DIALECT", "tsql"))
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
        normalized = expression.sql(dialect=getattr(settings, "SQL_DIALECT", "tsql"), pretty=False)
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
