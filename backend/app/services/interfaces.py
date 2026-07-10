from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.application_models.generated_report import GeneratedReport
from app.application_models.generated_sql import GeneratedSQL
from app.application_models.intent import IntentResult
from app.application_models.workflow_models import QueryResult
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
    async def render_sql_prompt(self, question: str, database_context: Optional[DatabaseContext] = None) -> str:
        """Retrieves db schema context, loads templates, and renders the combined SQL generation prompt.

        Args:
            question: The user question.
            database_context: Optional database context to bypass auto-retrieval.

        Returns:
            str: Complete system + SQL generation prompt.
        """
        pass

    @abstractmethod
    async def render_report_prompt(self, question: str, sql: str, query_result: QueryResult) -> str:
        """Loads templates and renders the combined report generation prompt.

        Args:
            question: The user question.
            sql: The executed SQL statement.
            query_result: Structured QueryResult database output DTO.

        Returns:
            str: Complete system + report generation prompt.
        """
        pass


class ISQLService(ABC):
    """Abstract interface defining contract for LLM SQL generation and safety verification."""

    @abstractmethod
    async def generate_sql(
        self,
        prompt: str,
        question: str | None = None,
        database_context: Optional[DatabaseContext] = None,
    ) -> GeneratedSQL:
        """Invokes LLM provider, extracts SQL syntax, performs safety validator checks, and returns metadata.

        Args:
            prompt: Pre-rendered safety prompt.
            question: Optional normalized question whose vocabulary is canonical for
                string literal values.
            database_context: Optional retrieved schema context used to validate
                that the SQL references only known tables and columns.

        Returns:
            GeneratedSQL: Structured SQL metadata DTO.
        """
        pass


class IReportService(ABC):
    """Abstract interface defining contract for narrative report synthesis."""

    @abstractmethod
    async def generate_report(
        self, question: str, sql: str, query_result: QueryResult, execution_id: Optional[str] = None
    ) -> GeneratedReport:
        """Invokes prompt services and LLM provider to synthesize a narrative report DTO.

        Args:
            question: User question context.
            sql: Executed SQL query.
            query_result: Structured QueryResult database output DTO.
            execution_id: Optional workflow run identifier.

        Returns:
            GeneratedReport: Narrative report DTO.
        """
        pass


class IWorkflowService(ABC):
    """Abstract interface defining contract for workflow orchestration across sub-services."""

    @abstractmethod
    async def execute_sql_generation(self, question: str, database_context: Optional[DatabaseContext] = None) -> GeneratedSQL:
        """Coordinates prompt rendering, SQL generation, and validation.

        Args:
            question: User query context.
            database_context: Optional database context to pass to prompt rendering.

        Returns:
            GeneratedSQL: The validated generated SQL DTO.
        """
        pass

    @abstractmethod
    async def execute_report_generation(
        self, question: str, sql: str, query_result: QueryResult, execution_id: Optional[str] = None
    ) -> GeneratedReport:
        """Coordinates narrative report generation.

        Args:
            question: User question.
            sql: Executed SQL.
            query_result: Structured QueryResult database output DTO.
            execution_id: Optional workflow run identifier.

        Returns:
            GeneratedReport: Final narrative report DTO.
        """
        pass

    @abstractmethod
    async def execute_query(self, sql: str) -> QueryResult:
        """Orchestrates query execution and maps result set DTO.

        Args:
            sql: Validated read-only SQL statement.

        Returns:
            QueryResult: The structured query results.
        """
        pass


class IExecutionService(ABC):
    """Abstract interface defining standard contract for SQL execution and mapping."""

    @abstractmethod
    async def execute_sql(self, sql: str) -> QueryResult:
        """Executes a validated SQL query statement, returning query result DTO.

        Args:
            sql: Validated read-only SQL string.

        Returns:
            QueryResult: The structured result set DTO.
        """
        pass


class IHelpService(ABC):
    """Abstract interface defining contract for displaying workflow user assistance."""

    @abstractmethod
    def get_help_markdown(self) -> str:
        """Returns the system guidance markdown text."""
        pass


class IIntentClassifier(ABC):
    """Abstract interface defining contract for classifying user intent.

    Current implementations are rule-based by design (mapping externalized keywords),
    but can be seamlessly swapped in future iterations for LLM-based or embedding-based
    classifiers without modifying the state graph or routing nodes.
    """

    @abstractmethod
    def classify(self, question: str) -> IntentResult:
        """Analyzes a natural language question and returns the classified IntentResult."""
        pass

