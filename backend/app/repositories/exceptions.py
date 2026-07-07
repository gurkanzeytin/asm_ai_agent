from app.shared.exceptions import AppBaseException


class RepositoryError(AppBaseException):
    """Base exception class for all repository data access failures."""

    pass


class EntityNotFoundError(RepositoryError):
    """Exception raised when a requested entity does not exist in database repositories."""

    pass
