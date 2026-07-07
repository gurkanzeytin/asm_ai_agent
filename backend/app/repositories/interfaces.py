from abc import ABC, abstractmethod
from typing import Any


class IAnalyticalRepository(ABC):
    """Abstract interface for read-heavy analytical query execution.

    Decouples AI query generator nodes and services from database drivers,
    focusing on read operations, metrics aggregation, and data profiling.
    """

    @abstractmethod
    async def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Executes a read-only query statement and returns list of dictionaries.

        Args:
            query: SQL statement string.
            params: Parameters dictionary for statement binding.

        Returns:
            list[dict]: List of row maps matching result sets.
        """
        pass

    @abstractmethod
    async def execute_scalar(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """Executes a query and returns the first column of the first row.

        Useful for analytical queries returning aggregates (e.g. COUNT, SUM, AVG).

        Args:
            query: SQL statement string.
            params: Parameters dictionary for statement binding.

        Returns:
            Any: Scalar value or None if result set is empty.
        """
        pass

    @abstractmethod
    async def fetch_paged_query(
        self, query: str, *, skip: int = 0, limit: int = 100, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Executes a query returning a paginated offset block.

        Args:
            query: SQL statement string.
            skip: Number of rows to offset.
            limit: Maximum number of rows to return.
            params: Parameters dictionary for statement binding.

        Returns:
            list[dict]: List of row maps matching result sets.
        """
        pass
