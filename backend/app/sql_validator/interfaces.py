from abc import ABC, abstractmethod

from app.sql_validator.models import SQLValidationResult


class ISQLValidator(ABC):
    """Abstract interface defining standard contract for SQL validation and diagnostics."""

    @abstractmethod
    def validate(self, sql: str) -> SQLValidationResult:
        """Validates query safety metrics, returning safety validation status and diagnostics.

        Args:
            sql: Raw SQL query string.

        Returns:
            SQLValidationResult: Result model representing query state and properties.
        """
        pass
