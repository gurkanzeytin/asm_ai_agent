from datetime import date
import logging
import time
from typing import Any, Dict, Optional

from app.application_models.generated_report import ReportPromptContext
from app.application_models.workflow_models import QueryResult
from app.core.config import settings
from app.database_intelligence.cache import SchemaCache
from app.database_intelligence.interfaces import ISchemaRetriever
from app.database_intelligence.models import DatabaseContext
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

    async def render_prompt(self, template_name: str, question: str, variables: Dict[str, Any]) -> str:
        """Loads prompt, retrieves schema context if required, and interpolates variables."""
        logger.info(
            "PromptService rendering prompt started.",
            extra={"template_name": template_name},
        )
        try:
            template_content = self.prompt_loader.get_prompt(template_name)

            enriched_vars = variables.copy()
            enriched_vars.setdefault("question", question)

            # If template has '{schema}' or '{metadata}' and it isn't in variables, auto-fetch schema
            if ("{schema}" in template_content or "{metadata}" in template_content) and (
                "schema" not in enriched_vars and "metadata" not in enriched_vars
            ):
                logger.info("Auto-retrieving schema context for template placeholders.")
                schema = await self.schema_cache.get_schema()
                db_context = self.schema_retriever.retrieve_context(question, schema)
                formatted_context = self._format_context(db_context)

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

    async def render_sql_prompt(self, question: str, database_context: Optional[DatabaseContext] = None) -> str:
        """Combines system prompt and SQL generation prompt with schema details."""
        try:
            t0 = time.perf_counter()
            system_prompt = await self.render_prompt("system_prompt.md", question, {})

            variables = {
                "dialect": getattr(settings, "SQL_DIALECT", "sqlite"),
                "current_date": date.today().isoformat(),
            }
            if database_context is not None:
                variables["schema"] = self._format_context(database_context)

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
                from datetime import datetime, timezone
                columns = list(query_result[0].keys()) if query_result else []
                query_result = QueryResult(
                    columns=columns,
                    rows=query_result,
                    row_count=len(query_result),
                    execution_time_ms=0.0,
                    success=True,
                    executed_at=datetime.now(timezone.utc),
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

    def _format_context(self, context: DatabaseContext) -> str:
        """Helper to format structured DatabaseContext metadata into a minimal prompt representation.

        Omits table comments, column comments, nullability constraints, and column defaults
        to save context tokens, while preserving exact table, column, and foreign key structures.
        """
        lines = []
        for table in context.tables:
            lines.append(f"Table: {table.name}")
            cols = [
                f"{col.name} ({col.type_name}){' [PK]' if col.primary_key else ''}"
                for col in table.columns
            ]
            lines.append(f"  Columns: {', '.join(cols)}")
            if table.foreign_keys:
                fks = [
                    f"({', '.join(fk.constrained_columns)})->{fk.referred_table}({', '.join(fk.referred_columns)})"
                    for fk in table.foreign_keys
                ]
                lines.append(f"  Foreign Keys: {', '.join(fks)}")
            lines.append("")
        return "\n".join(lines).strip()


    def _log_prompt_stats(
        self,
        rendered: str,
        database_context: Optional[DatabaseContext],
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
            "Prompt statistics [%s]: chars=%d estimated_tokens=%d tables=%d columns=%d render_ms=%.1f",
            label,
            char_count,
            estimated_tokens,
            table_count,
            column_count,
            render_ms,
        )
