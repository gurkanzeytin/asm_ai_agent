from app.shared.exceptions import AppBaseException


class SQLValidationException(AppBaseException):
    """Base exception class for all safety validation errors."""

    pass


class SQLParsingException(SQLValidationException):
    """Raised when queries cannot be parsed due to syntactic or lexical violations."""

    pass


class UnsafeSQLException(SQLValidationException):
    """Raised when queries violate safety parameters (e.g. database mutations)."""

    pass
