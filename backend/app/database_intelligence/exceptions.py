from app.shared.exceptions import AppBaseException


class DatabaseInspectionError(AppBaseException):
    """Raised when database schema metadata inspection fails."""

    pass


class SchemaCacheError(AppBaseException):
    """Raised when database schema cache operations fail."""

    pass


class SchemaRetrievalError(AppBaseException):
    """Raised when schema retrieval or filtering logic fails."""

    pass
