from app.shared.exceptions import AppBaseException


class ApplicationServiceException(AppBaseException):
    """Base exception class for all application services."""

    pass


class PromptServiceException(ApplicationServiceException):
    """Raised when prompt template loading, rendering, or formatting fails."""

    pass


class SQLServiceException(ApplicationServiceException):
    """Raised when SQL query generation, translation, or validation fails."""

    pass


class ReportServiceException(ApplicationServiceException):
    """Raised when report synthesis or narrative layout parsing fails."""

    pass


class WorkflowServiceException(ApplicationServiceException):
    """Raised when workflow orchestration steps encounter errors."""

    pass


class ExecutionServiceException(ApplicationServiceException):
    """Raised when execution service operations encounter general issues."""

    pass


class QueryExecutionException(ExecutionServiceException):
    """Raised when query execution fails at the repository database boundary."""

    pass
