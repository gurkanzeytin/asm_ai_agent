from datetime import date
import logging
from typing import Any, Dict

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

    async def render_sql_prompt(self, question: str) -> str:
        """Combines system prompt and SQL generation prompt with schema details."""
        try:
            system_prompt = await self.render_prompt("system_prompt.md", question, {})
            sql_prompt = await self.render_prompt(
                "sql_generation.md",
                question,
                {
                    "dialect": getattr(settings, "SQL_DIALECT", "sqlite"),
                    "current_date": date.today().isoformat(),
                },
            )
            return f"{system_prompt}\n\n{sql_prompt}"
        except Exception as e:
            logger.error(f"Failed to render SQL prompt: {e}")
            raise PromptServiceException(f"Failed to render SQL prompt: {e}") from e

    async def render_report_prompt(self, question: str, sql: str, query_result: list) -> str:
        """Combines system prompt and report generation prompt with query execution outputs."""
        try:
            system_prompt = await self.render_prompt("system_prompt.md", question, {})
            report_prompt = await self.render_prompt(
                "report_generation.md",
                question,
                {"query": sql, "results": str(query_result)},
            )
            return f"{system_prompt}\n\n{report_prompt}"
        except Exception as e:
            logger.error(f"Failed to render report prompt: {e}")
            raise PromptServiceException(f"Failed to render report prompt: {e}") from e

    def _format_context(self, context: DatabaseContext) -> str:
        """Helper to format structured DatabaseContext metadata into prompt text representation."""
        lines = []
        for table in context.tables:
            lines.append(f"Table: {table.name}")
            if table.comment:
                lines.append(f"  Description: {table.comment}")
            lines.append("  Columns:")
            for col in table.columns:
                col_info = f"    - {col.name} ({col.type_name})"
                extra = []
                if col.primary_key:
                    extra.append("PK")
                if not col.nullable:
                    extra.append("NOT NULL")
                if col.default:
                    extra.append(f"DEFAULT {col.default}")
                if col.comment:
                    extra.append(f"Comment: {col.comment}")
                if extra:
                    col_info += f" [{', '.join(extra)}]"
                lines.append(col_info)
            if table.foreign_keys:
                lines.append("  Foreign Keys:")
                for fk in table.foreign_keys:
                    lines.append(
                        f"    - ({', '.join(fk.constrained_columns)}) -> {fk.referred_table}({', '.join(fk.referred_columns)})"
                    )
            lines.append("")
        return "\n".join(lines).strip()
