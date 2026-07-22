import logging
import time
from datetime import datetime, timezone

from app.application_models.workflow_models import QueryResult
from app.core.config import settings
from app.repositories.interfaces import IAnalyticalRepository
from app.services.exceptions import QueryExecutionException
from app.services.interfaces import IExecutionService
from app.shared.result_limits import (
    DEFAULT_TABLE_PAGE_SIZE,
    MAX_DATABASE_FETCH_ROWS,
)
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
        url = settings.DATABASE_URL or ""
        provider = "mssql" if url.startswith("mssql") else "unknown"

        # 3. Trigger execution on the repository
        try:
            fetched_rows = await self.repository.execute_readonly_query(sql)
            duration_ms = (time.perf_counter() - start_time) * 1000

            has_more = len(fetched_rows) > MAX_DATABASE_FETCH_ROWS
            rows = fetched_rows[:MAX_DATABASE_FETCH_ROWS]

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
                returned_row_count=row_count,
                displayed_row_count=min(row_count, DEFAULT_TABLE_PAGE_SIZE),
                result_truncated=has_more,
                applied_limit=MAX_DATABASE_FETCH_ROWS,
                has_more=has_more,
                total_count=None,
            )

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"ExecutionService failed during database query execution: {e}")
            raise QueryExecutionException(f"Query execution failed: {e}") from e
