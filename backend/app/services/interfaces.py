from abc import ABC, abstractmethod
from typing import Any, Dict

from app.application_models.generated_report import GeneratedReport
from app.application_models.generated_sql import GeneratedSQL
from app.database_intelligence.models import DatabaseContext


class IPromptService(ABC):
    """Abstract interface defining contract for prompt loading, context extraction, and rendering."""

    @abstractmethod
    async def retrieve_schema_context(self, question: str) -> DatabaseContext:
        """Retrieves matching database schema context structured metadata.

        Args:
            question: The user query context.

        Returns:
            DatabaseContext: Discovered database context object.
        """
        pass

    @abstractmethod
    async def render_prompt(self, template_name: str, question: str, variables: Dict[str, Any]) -> str:
        """Loads and interpolates variables into a target prompt template.

        Args:
            template_name: Target template filename.
            question: The user query string.
            variables: Parameters to inject into the placeholders.

        Returns:
            str: Rendered prompt text.
        """
        pass

    @abstractmethod
    async def render_sql_prompt(self, question: str) -> str:
        """Retrieves db schema context, loads templates, and renders the combined SQL generation prompt.

        Args:
            question: The user question.

        Returns:
            str: Complete system + SQL generation prompt.
        """
        pass

    @abstractmethod
    async def render_report_prompt(self, question: str, sql: str, query_result: list) -> str:
        """Loads templates and renders the combined report generation prompt.

        Args:
            question: The user question.
            sql: The executed SQL statement.
            query_result: List of query rows from database.

        Returns:
            str: Complete system + report generation prompt.
        """
        pass


class ISQLService(ABC):
    """Abstract interface defining contract for LLM SQL generation and safety verification."""

    @abstractmethod
    async def generate_sql(self, prompt: str) -> GeneratedSQL:
        """Invokes LLM provider, extracts SQL syntax, performs safety validator checks, and returns metadata.

        Args:
            prompt: Pre-rendered safety prompt.

        Returns:
            GeneratedSQL: Structured SQL metadata DTO.
        """
        pass


class IReportService(ABC):
    """Abstract interface defining contract for narrative report synthesis."""

    @abstractmethod
    async def generate_report(self, question: str, sql: str, query_result: list) -> GeneratedReport:
        """Invokes prompt services and LLM provider to synthesize a narrative report DTO.

        Args:
            question: User question context.
            sql: Executed SQL query.
            query_result: Returned database rows list.

        Returns:
            GeneratedReport: Narrative report DTO.
        """
        pass


class IWorkflowService(ABC):
    """Abstract interface defining contract for workflow orchestration across sub-services."""

    @abstractmethod
    async def execute_sql_generation(self, question: str) -> GeneratedSQL:
        """Coordinates prompt rendering, SQL generation, and validation.

        Args:
            question: User query context.

        Returns:
            GeneratedSQL: The validated generated SQL DTO.
        """
        pass

    @abstractmethod
    async def execute_report_generation(self, question: str, sql: str, query_result: list) -> GeneratedReport:
        """Coordinates narrative report generation.

        Args:
            question: User question.
            sql: Executed SQL.
            query_result: Database output rows.

        Returns:
            GeneratedReport: Final narrative report DTO.
        """
        pass
