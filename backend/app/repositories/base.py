import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.exceptions import RepositoryError
from app.repositories.interfaces import IAnalyticalRepository

logger = logging.getLogger(__name__)


class AnalyticalRepository(IAnalyticalRepository):
    """SQLAlchemy AsyncSession implementation of the IAnalyticalRepository interface.

    Optimized for read-heavy workloads. Encapsulates execution of read-only statements,
    telemetry measurements, logging, and transactional database mapping boundaries.
    """

    def __init__(self, session: AsyncSession):
        """Constructor dependency injection.

        Args:
            session: Active database AsyncSession connection context.
        """
        logger.debug("Initializing AnalyticalRepository query engine.")
        self.session = session

    async def execute_readonly_query(self, sql: str) -> list[dict[str, Any]]:
        """Executes a validated read-only SQL query and returns list of dict rows."""
        return await self.execute_query(sql)

    async def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Executes a read-only query statement and returns list of dictionaries."""
        logger.info(f"AnalyticalRepository executing query statement (length={len(query)})...")
        start = time.perf_counter()
        try:
            result = await self.session.execute(text(query), params or {})
            if result.returns_rows:
                return [dict(row) for row in result.mappings().all()]
            return []
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise RepositoryError(f"Database query execution failed: {str(e)}") from e
        finally:
            logger.info(
                f"Execution profile [execute_query]: elapsed={time.perf_counter() - start:.6f}s"
            )

    async def execute_scalar(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """Executes a query and returns the first column of the first row."""
        logger.info(f"AnalyticalRepository executing scalar query (length={len(query)})...")
        start = time.perf_counter()
        try:
            result = await self.session.execute(text(query), params or {})
            return result.scalar()
        except Exception as e:
            logger.error(f"Scalar query execution failed: {e}")
            raise RepositoryError(f"Database scalar query failed: {str(e)}") from e
        finally:
            logger.info(
                f"Execution profile [execute_scalar]: elapsed={time.perf_counter() - start:.6f}s"
            )

    async def fetch_paged_query(
        self, query: str, *, skip: int = 0, limit: int = 100, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Executes a query returning a paginated offset block."""
        logger.info(f"AnalyticalRepository fetching paged query (skip={skip}, limit={limit})...")
        # Simple SQL formatting. In advanced productions, utilize AST parsers (e.g. sqlglot)
        query_clean = query.strip().rstrip(";")
        paged_query = f"{query_clean} LIMIT {limit} OFFSET {skip};"
        return await self.execute_query(paged_query, params)


class ScopedAnalyticalRepository(IAnalyticalRepository):
    """Session-scoped proxy implementation of the IAnalyticalRepository interface.

    Wraps the underlying AnalyticalRepository to automatically obtain and close
    short-lived AsyncSession instances from the session factory per query execution.
    This guarantees concurrency safety in multi-threaded/async request pools.
    """

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        """Constructor dependency injection.

        Args:
            session_maker: Factory producing AsyncSession connections.
        """
        self.session_maker = session_maker

    async def execute_readonly_query(self, sql: str) -> list[dict[str, Any]]:
        """Obtains scoped session and runs execution."""
        async with self.session_maker() as session:
            repo = AnalyticalRepository(session)
            return await repo.execute_readonly_query(sql)

    async def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Obtains scoped session and runs execution."""
        async with self.session_maker() as session:
            repo = AnalyticalRepository(session)
            return await repo.execute_query(query, params)

    async def execute_scalar(self, query: str, params: dict[str, Any] | None = None) -> Any:
        """Obtains scoped session and runs execution."""
        async with self.session_maker() as session:
            repo = AnalyticalRepository(session)
            return await repo.execute_scalar(query, params)

    async def fetch_paged_query(
        self, query: str, *, skip: int = 0, limit: int = 100, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Obtains scoped session and runs execution."""
        async with self.session_maker() as session:
            repo = AnalyticalRepository(session)
            return await repo.fetch_paged_query(query, skip=skip, limit=limit, params=params)
