import logging
import time
from typing import Any

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.repositories.exceptions import RepositoryError
from app.repositories.interfaces import IAnalyticalRepository

logger = logging.getLogger(__name__)


def _database_provider() -> str:
    """Derives the active database provider family from the configured URL."""
    url = settings.DATABASE_URL or ""
    if url.startswith("mssql"):
        return "mssql"
    if url.startswith("postgresql") or url.startswith("postgres"):
        return "postgresql"
    return "sqlite"


def build_paged_query(query: str, provider: str) -> str:
    """Builds a dialect-correct paginated SQL statement with bound :skip and :limit params.

    SQL Server does not support LIMIT/OFFSET; it requires ORDER BY ... OFFSET ... FETCH.
    When the query has no ORDER BY, the deterministic-neutral 'ORDER BY (SELECT NULL)'
    bounded strategy is used. Queries already bounded by TOP are wrapped in a subquery
    because TOP cannot be combined with OFFSET/FETCH at the same query level.
    """
    query_clean = query.strip().rstrip(";")
    if provider != "mssql":
        return f"{query_clean} LIMIT :limit OFFSET :skip;"

    has_order_by = False
    has_top = False
    try:
        expression = sqlglot.parse_one(query_clean, read="tsql")
        if expression is not None:
            has_order_by = expression.args.get("order") is not None
            has_top = expression.args.get("limit") is not None
    except Exception:
        logger.warning("Pagination could not parse query AST; using bounded wrapper strategy.")
        has_top = True  # Fall through to the safe subquery wrapper

    if has_top:
        return (
            f"SELECT * FROM ({query_clean}) AS paged_query "
            f"ORDER BY (SELECT NULL) OFFSET :skip ROWS FETCH NEXT :limit ROWS ONLY;"
        )
    if has_order_by:
        return f"{query_clean} OFFSET :skip ROWS FETCH NEXT :limit ROWS ONLY;"
    return f"{query_clean} ORDER BY (SELECT NULL) OFFSET :skip ROWS FETCH NEXT :limit ROWS ONLY;"


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
        """Executes a query returning a paginated offset block using dialect-correct SQL."""
        logger.info(f"AnalyticalRepository fetching paged query (skip={skip}, limit={limit})...")
        if skip < 0:
            raise RepositoryError("Pagination 'skip' must be greater than or equal to 0.")
        max_limit = settings.DATABASE_MAX_PAGE_SIZE
        if limit < 1 or limit > max_limit:
            raise RepositoryError(f"Pagination 'limit' must be between 1 and {max_limit}.")

        paged_query = build_paged_query(query, _database_provider())
        merged_params = {**(params or {}), "skip": skip, "limit": limit}
        return await self.execute_query(paged_query, merged_params)


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
