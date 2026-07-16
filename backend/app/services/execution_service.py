from datetime import datetime, timezone
import logging
import time

from app.application_models.workflow_models import QueryResult
from app.core.config import settings
from app.repositories.interfaces import IAnalyticalRepository
from app.services.exceptions import QueryExecutionException
from app.services.interfaces import IExecutionService
from app.sql_validator.interfaces import ISQLValidator

logger = logging.getLogger(__name__)


class ExecutionService(IExecutionService):
    """ExecutionService coordinates validated read-only SQL statement run profiling."""

    def __init__(self, repository: IAnalyticalRepository, sql_validator: ISQLValidator):
        self.repository = repository
        self.sql_validator = sql_validator

    async def execute_sql(self, sql: str) -> QueryResult:
        logger.info("ExecutionService starting SQL statement execution pipeline.")
        start_time = time.perf_counter()
        executed_at = datetime.now(timezone.utc)

        # 1. Perform read-only safety assertion validation
        try:
            validation_result = self.sql_validator.validate(sql)
        except Exception as ve:
            logger.error(f"SQL validation call encountered unexpected failure: {ve}")
            raise QueryExecutionException(f"SQL validation call failed: {ve}") from ve

        if not validation_result.valid:
            reason = validation_result.reason or "Safety checker rules validation failed."
            logger.error(f"Read-only safety assertion validation failed: {reason}")
            raise QueryExecutionException(f"Read-only safety assertion failed: {reason}")

        # 2. Extract database engine provider dynamically (never expose the URL itself)
        provider = "unknown"
        url = settings.DATABASE_URL or ""
        if url.startswith("sqlite"):
            provider = "sqlite"
        elif url.startswith("postgresql") or url.startswith("postgres"):
            provider = "postgresql"
        elif url.startswith("mssql"):
            provider = "mssql"

        # 3. Trigger execution on the repository
        try:
            rows = await self.repository.execute_readonly_query(sql)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Dynamic columns parse mapping
            columns = list(rows[0].keys()) if rows else []
            row_count = len(rows)

            logger.info(
                "ExecutionService completed query execution successfully.",
                extra={
                    "duration_ms": duration_ms,
                    "row_count": row_count,
                },
            )

            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=row_count,
                execution_time_ms=duration_ms,
                success=True,
                executed_at=executed_at,
                database_provider=provider,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"ExecutionService failed during database query execution: {e}")
            raise QueryExecutionException(f"Query execution failed: {e}") from e
