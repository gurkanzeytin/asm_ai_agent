from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_reporting_service
from app.application_models.workflow_result import WorkflowResult
from app.schemas.report import (
    MetadataSchema,
    QueryResultSchema,
    ReportRequest,
    ReportResponse,
    ReportSchema,
)
from app.services.reporting_service import ReportingService

router = APIRouter()


def _map_to_response(result: WorkflowResult) -> ReportResponse:
    """Maps a WorkflowResult application DTO to the API transport ReportResponse schema.

    This is the only location where internal models are translated to API contracts.
    No business logic lives here — structural mapping only.
    """
    query_result_schema = None
    if result.query_result:
        qr = result.query_result
        query_result_schema = QueryResultSchema(
            columns=qr.columns,
            rows=qr.rows,
            row_count=qr.row_count,
        )

    report_schema = None
    if result.generated_report:
        rpt = result.generated_report
        report_schema = ReportSchema(
            title=rpt.title,
            markdown=rpt.markdown,
        )

    metadata_schema = None
    if result.generated_report:
        rpt = result.generated_report
        metadata_schema = MetadataSchema(
            provider=rpt.provider,
            model=rpt.model,
            latency_ms=rpt.latency_ms,
            prompt_tokens=rpt.prompt_tokens,
            completion_tokens=rpt.completion_tokens,
        )

    return ReportResponse(
        success=len(result.errors) == 0,
        workflow_id=result.workflow_id,
        question=result.question,
        generated_sql=result.generated_sql,
        query_result=query_result_schema,
        report=report_schema,
        metadata=metadata_schema,
    )


@router.post(
    "/",
    response_model=ReportResponse,
    summary="Generate an AI analytical report",
    description=(
        "Accepts a natural-language question and runs the complete AI workflow: "
        "schema context retrieval → SQL generation → SQL validation → database execution → "
        "narrative report synthesis. Returns structured results including the generated SQL, "
        "database result rows, and a markdown narrative report."
    ),
    responses={
        200: {"description": "Workflow completed successfully.", "model": ReportResponse},
        400: {"description": "Query execution or SQL validation failure."},
        502: {"description": "LLM provider failed to generate the report."},
        500: {"description": "Internal workflow error."},
    },
)
async def generate_report(
    request: ReportRequest,
    reporting_service: Annotated[ReportingService, Depends(get_reporting_service)],
) -> ReportResponse:
    """Runs the full AI reporting workflow for the provided natural-language question."""
    result = await reporting_service.run_workflow(request.question)
    return _map_to_response(result)
