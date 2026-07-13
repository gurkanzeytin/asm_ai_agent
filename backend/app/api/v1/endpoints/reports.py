from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_reporting_service
from app.application_models.workflow_result import WorkflowResult
from app.schemas.report import (
    AnalyticsSchema,
    InsightSchema,
    ObservationItemSchema,
    ObservationsSchema,
    MetadataSchema,
    QueryResultSchema,
    ReportRequest,
    ReportResponse,
    ReportSchema,
    TimingSchema,
    IntentSchema,
    VisualizationSchema,
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

    timing_schema = None
    if result.metrics:
        m = result.metrics
        timing_schema = TimingSchema(
            analyze_intent_ms=m.analyze_intent_ms,
            analyze_results_ms=m.analyze_results_ms,
            generate_insights_ms=m.generate_insights_ms,
            generate_observations_ms=m.generate_observations_ms,
            retrieve_context_ms=m.retrieve_context_ms,
            generate_sql_ms=m.generate_sql_ms,
            validate_sql_ms=m.validate_sql_ms,
            execute_sql_ms=m.execute_sql_ms,
            generate_report_ms=m.generate_report_ms,
            llm_total_ms=m.llm_total_ms,
            total_ms=m.total_ms,
        )

    intent_schema = None
    if result.intent:
        it = result.intent
        intent_schema = IntentSchema(
            intent=it.intent.value,
            confidence=it.confidence,
            reason=it.reason,
            matched_keywords=it.matched_keywords,
            metadata=it.metadata,
        )

    analytics_schema = None
    visualization_schema = None
    if result.analytics:
        an = result.analytics
        if an.visualization:
            visualization_schema = VisualizationSchema(
                type=an.visualization.type.value,
                reason=an.visualization.reason,
            )
        analytics_schema = AnalyticsSchema(
            analytics_type=an.analytics_type,
            intents=[intent.value for intent in an.intents],
            data_shape=an.data_shape.value,
            metrics=an.metrics,
            insights=an.insights,
            visualization=visualization_schema,
            row_count=an.row_count,
        )

    insight_schema = None
    if result.insights:
        ins = result.insights
        insight_schema = InsightSchema(
            title=ins.title,
            summary=ins.summary,
            highlights=ins.highlights,
            observations=ins.observations,
            considerations=ins.considerations,
            rules=[rule.value for rule in ins.rules],
            confidence=ins.confidence.value,
            llm_generated=ins.llm_generated,
        )

    observations_schema = None
    if result.observations:
        obs = result.observations
        observations_schema = ObservationsSchema(
            observations=[
                ObservationItemSchema(
                    rule=item.rule,
                    category=item.category.value,
                    text=item.text,
                    evidence=item.evidence,
                )
                for item in obs.observations
            ],
            confidence=obs.confidence.value,
            llm_worded=obs.llm_worded,
        )

    return ReportResponse(
        success=len(result.errors) == 0,
        workflow_id=result.workflow_id,
        question=result.question,
        generated_sql=result.generated_sql,
        query_result=query_result_schema,
        report=report_schema,
        metadata=metadata_schema,
        timing=timing_schema,
        intent=intent_schema,
        analytics=analytics_schema,
        insights=insight_schema,
        observations=observations_schema,
        visualization=visualization_schema,
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
