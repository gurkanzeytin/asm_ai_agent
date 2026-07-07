import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.exceptions import (
    QueryExecutionException,
    ReportServiceException,
    SQLServiceException,
    WorkflowServiceException,
)
from app.shared.exceptions import AppBaseException, SQLSafetyViolation

logger = logging.getLogger(__name__)


def _error_response(status_code: int, error_code: str, message: str) -> JSONResponse:
    """Builds a standardised JSON error envelope.

    Stack traces are never included in the response body.
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error_code": error_code,
            "message": message,
        },
    )


async def handle_query_execution_exception(
    request: Request, exc: QueryExecutionException
) -> JSONResponse:
    """Maps QueryExecutionException → HTTP 400."""
    logger.warning(f"QueryExecutionException on {request.url.path}: {exc}")
    return _error_response(400, "QUERY_EXECUTION_ERROR", "The query could not be executed against the database.")


async def handle_sql_safety_violation(
    request: Request, exc: SQLSafetyViolation
) -> JSONResponse:
    """Maps SQLSafetyViolation → HTTP 400."""
    logger.warning(f"SQLSafetyViolation on {request.url.path}: {exc}")
    return _error_response(400, "SQL_VALIDATION_ERROR", "The generated SQL statement failed safety validation.")


async def handle_sql_service_exception(
    request: Request, exc: SQLServiceException
) -> JSONResponse:
    """Maps SQLServiceException → HTTP 400."""
    logger.warning(f"SQLServiceException on {request.url.path}: {exc}")
    return _error_response(400, "SQL_GENERATION_ERROR", "The LLM could not generate a valid SQL statement for this question.")


async def handle_report_service_exception(
    request: Request, exc: ReportServiceException
) -> JSONResponse:
    """Maps ReportServiceException (LLM failure) → HTTP 502."""
    logger.error(f"ReportServiceException on {request.url.path}: {exc}")
    return _error_response(502, "LLM_ERROR", "The language model failed to generate the report. Please try again.")


async def handle_workflow_service_exception(
    request: Request, exc: WorkflowServiceException
) -> JSONResponse:
    """Maps WorkflowServiceException → HTTP 500."""
    logger.error(f"WorkflowServiceException on {request.url.path}: {exc}")
    return _error_response(500, "WORKFLOW_ERROR", "An internal workflow error occurred. The request could not be completed.")


async def handle_app_base_exception(
    request: Request, exc: AppBaseException
) -> JSONResponse:
    """Catch-all for unclassified domain exceptions → HTTP 500."""
    logger.error(f"Unhandled AppBaseException on {request.url.path}: {exc}")
    return _error_response(500, "INTERNAL_ERROR", "An unexpected internal error occurred.")


# Ordered registration list: most specific exceptions first.
EXCEPTION_HANDLERS = [
    (QueryExecutionException, handle_query_execution_exception),
    (SQLSafetyViolation, handle_sql_safety_violation),
    (SQLServiceException, handle_sql_service_exception),
    (ReportServiceException, handle_report_service_exception),
    (WorkflowServiceException, handle_workflow_service_exception),
    (AppBaseException, handle_app_base_exception),
]
