class AppBaseException(Exception):
    """Base exception class for all custom domain errors."""

    pass


class AgentWorkflowError(AppBaseException):
    """Raised if errors occur during agent state machine graph nodes execution."""

    pass


class DatabaseExecutionError(AppBaseException):
    """Raised when raw database query execution fails."""

    pass


class SQLSafetyViolation(AppBaseException):
    """Raised when queries violate read-only safety checks."""

    pass


class ConfigurationError(AppBaseException):
    """Exception raised when LLM provider or application configurations are invalid or missing."""

    pass
