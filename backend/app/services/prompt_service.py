import logging
import re
import time
import unicodedata
from datetime import UTC, date
from typing import Any

from app.application_models.generated_report import ReportPromptContext
from app.application_models.workflow_models import QueryResult
from app.core.config import settings
from app.database_intelligence.cache import SchemaCache
from app.database_intelligence.interfaces import ISchemaRetriever
from app.database_intelligence.models import DatabaseContext
from app.database_intelligence.synonyms import SYNONYM_MAP
from app.prompts.loader import PromptLoader
from app.prompts.renderer import IPromptRenderer
from app.services.exceptions import PromptServiceException
from app.services.interfaces import IPromptService

logger = logging.getLogger(__name__)


class PromptService(IPromptService):
    """Orchestrates schema context loading, template retrieval, and rendering of prompts."""

    def __init__(
        self,
        schema_cache: SchemaCache,
        schema_retriever: ISchemaRetriever,
        prompt_loader: PromptLoader,
        prompt_renderer: IPromptRenderer,
    ):
        self.schema_cache = schema_cache
        self.schema_retriever = schema_retriever
        self.prompt_loader = prompt_loader
        self.prompt_renderer = prompt_renderer

    async def retrieve_schema_context(self, question: str) -> DatabaseContext:
        """Retrieves matching database schema context structured metadata."""
        try:
            schema = await self.schema_cache.get_schema()
            return self.schema_retriever.retrieve_context(question, schema)
        except Exception as e:
            logger.error(f"Failed to retrieve schema context: {e}")
            raise PromptServiceException(f"Failed to retrieve schema context: {e}") from e

    async def render_prompt(
        self,
        template_name: str,
        question: str,
        variables: dict[str, Any],
    ) -> str:
        """Loads prompt, retrieves schema context if required, and interpolates variables."""
        logger.info(
            "PromptService rendering prompt started.",
            extra={"template_name": template_name},
        )
        try:
            template_content = self.prompt_loader.get_prompt(template_name)

            enriched_vars = variables.copy()
            enriched_vars.setdefault("question", question)

            # Auto-fetch schema when the template asks for schema or metadata.
            if ("{schema}" in template_content or "{metadata}" in template_content) and (
                "schema" not in enriched_vars and "metadata" not in enriched_vars
            ):
                logger.info("Auto-retrieving schema context for template placeholders.")
                schema = await self.schema_cache.get_schema()
                db_context = self.schema_retriever.retrieve_context(question, schema)
                formatted_context = self._format_context(db_context, question=question)

                if not formatted_context.strip():
                    raise PromptServiceException(
                        "Schema context resolved to empty string. "
                        "The database schema may be empty or the retriever returned no tables."
                    )

                if "{schema}" in template_content:
                    enriched_vars["schema"] = formatted_context
                if "{metadata}" in template_content:
                    enriched_vars["metadata"] = formatted_context

            rendered = self.prompt_renderer.render(template_content, enriched_vars)

            logger.info(
                "PromptService rendering prompt completed successfully.",
                extra={"template_name": template_name, "rendered_length": len(rendered)},
            )
            return rendered

        except Exception as e:
            logger.error(f"PromptService failed to render template '{template_name}': {e}")
            raise PromptServiceException(f"Failed to render template '{template_name}': {e}") from e

    async def render_sql_prompt(
        self,
        question: str,
        database_context: DatabaseContext | None = None,
    ) -> str:
        """Combines system prompt and SQL generation prompt with schema details."""
        try:
            t0 = time.perf_counter()
            system_prompt = await self.render_prompt("system_prompt.md", question, {})

            variables = {
                "dialect": getattr(settings, "SQL_DIALECT", "sqlite"),
                "current_date": date.today().isoformat(),
            }
            if database_context is not None:
                variables["schema"] = self._format_context(database_context, question=question)

            sql_prompt = await self.render_prompt(
                "sql_generation.md",
                question,
                variables,
            )
            combined = f"{system_prompt}\n\n{sql_prompt}"
            render_ms = (time.perf_counter() - t0) * 1000
            self._log_prompt_stats(combined, database_context, render_ms, label="sql")
            return combined
        except Exception as e:
            logger.error(f"Failed to render SQL prompt: {e}")
            raise PromptServiceException(f"Failed to render SQL prompt: {e}") from e

    async def render_report_prompt(self, question: str, sql: str, query_result: QueryResult) -> str:
        """Combines system prompt and report generation prompt with query execution outputs."""
        try:
            t0 = time.perf_counter()
            system_prompt = await self.render_prompt("system_prompt.md", question, {})

            # Dynamic conversion for legacy test compatibility
            if isinstance(query_result, list):
                from datetime import datetime
                columns = list(query_result[0].keys()) if query_result else []
                query_result = QueryResult(
                    columns=columns,
                    rows=query_result,
                    row_count=len(query_result),
                    execution_time_ms=0.0,
                    success=True,
                    executed_at=datetime.now(UTC),
                    database_provider="sqlite",
                )

            # Truncate rows if necessary to protect against large datasets
            original_row_count = query_result.row_count
            rows = query_result.rows
            truncated_row_count = None
            max_rows = getattr(settings, "REPORT_MAX_ROWS", 100)
            if len(rows) > max_rows:
                rows = rows[:max_rows]
                truncated_row_count = len(rows)

            # Build ReportPromptContext DTO
            context = ReportPromptContext(
                question=question,
                columns=query_result.columns,
                rows=rows,
                original_row_count=original_row_count,
                truncated_row_count=truncated_row_count,
            )

            # Serialize context DTO to JSON format
            serialized_context = context.model_dump_json(indent=2)

            report_prompt = await self.render_prompt(
                "report_generation.md",
                question,
                {
                    "query": sql,
                    "results": serialized_context,
                },
            )
            combined = f"{system_prompt}\n\n{report_prompt}"
            render_ms = (time.perf_counter() - t0) * 1000
            self._log_prompt_stats(combined, None, render_ms, label="report")
            return combined
        except Exception as e:
            logger.error(f"Failed to render report prompt: {e}")
            raise PromptServiceException(f"Failed to render report prompt: {e}") from e

    def _format_context(self, context: DatabaseContext, question: str | None = None) -> str:
        """Formats structured DatabaseContext metadata into compact prompt text.

        Omits table comments, column comments, nullability constraints, and column defaults
        to save context tokens, while preserving exact table, column, and foreign key structures.
        """
        query_tokens = self._query_tokens(question or "")
        lines = []
        for table in context.tables:
            lines.append(f"Table: {table.name}")
            selected_columns = self._select_relevant_columns(table, query_tokens)
            cols = [
                f"{col.name} ({col.type_name}){' [PK]' if col.primary_key else ''}"
                for col in selected_columns
            ]
            lines.append(f"  Columns: {', '.join(cols)}")
            if table.foreign_keys:
                fks = [
                    f"({', '.join(fk.constrained_columns)})->"
                    f"{fk.referred_table}({', '.join(fk.referred_columns)})"
                    for fk in table.foreign_keys
                ]
                lines.append(f"  Foreign Keys: {', '.join(fks)}")
            lines.append("")
        return "\n".join(lines).strip()

    def _select_relevant_columns(self, table, query_tokens: set[str]):
        """Selects compact table columns while preserving joinability and common labels."""
        if len(table.columns) <= 2:
            return table.columns

        max_columns = min(getattr(settings, "SCHEMA_MAX_COLUMNS", 15), 6)
        pk_names = set(table.primary_keys)
        fk_names = {col for fk in table.foreign_keys for col in fk.constrained_columns}
        selected = []

        def add_column(column):
            if column not in selected:
                selected.append(column)

        for column in table.columns:
            if column.primary_key or column.name in pk_names or column.name in fk_names:
                add_column(column)

        for column in table.columns:
            if self._is_column_relevant(column.name, query_tokens):
                add_column(column)

        for column in table.columns:
            if self._is_priority_column(column.name):
                add_column(column)

        for column in table.columns:
            if len(selected) >= max_columns:
                break
            add_column(column)

        return selected[:max_columns]

    def _is_column_relevant(self, column_name: str, query_tokens: set[str]) -> bool:
        column_tokens = self._query_tokens(column_name)
        return bool(column_tokens.intersection(query_tokens))

    def _is_priority_column(self, column_name: str) -> bool:
        normalized = self._normalize_text(column_name)
        tokens = set(re.findall(r"\w+", normalized))
        exact_priority = {"ad", "adi", "ad_soyad", "name", "durum", "status", "tutar", "puan"}
        metric_or_temporal = ("tarih", "date", "sayi", "count")
        return bool(tokens.intersection(exact_priority)) or any(
            marker in normalized for marker in metric_or_temporal
        )

    def _query_tokens(self, text: str) -> set[str]:
        normalized = self._normalize_text(text)
        tokens = set(re.findall(r"\w+", normalized))
        expanded = set(tokens)
        for token in tokens:
            expanded.update(SYNONYM_MAP.get(token, []))
        return expanded

    def _normalize_text(self, text: str) -> str:
        text = text.lower().translate(
            str.maketrans(
                {
                    "ı": "i",
                    "ğ": "g",
                    "ş": "s",
                    "ç": "c",
                    "ö": "o",
                    "ü": "u",
                }
            )
        )
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(char for char in normalized if not unicodedata.combining(char))


    def _log_prompt_stats(
        self,
        rendered: str,
        database_context: DatabaseContext | None,
        render_ms: float,
        label: str = "prompt",
    ) -> None:
        """Logs prompt statistics at INFO level. No prompt contents are logged."""
        char_count = len(rendered)
        estimated_tokens = char_count // 4
        table_count = len(database_context.tables) if database_context else 0
        column_count = (
            sum(len(t.columns) for t in database_context.tables) if database_context else 0
        )
        logger.info(
            "Prompt statistics [%s]: chars=%d estimated_tokens=%d tables=%d "
            "columns=%d render_ms=%.1f",
            label,
            char_count,
            estimated_tokens,
            table_count,
            column_count,
            render_ms,
        )
