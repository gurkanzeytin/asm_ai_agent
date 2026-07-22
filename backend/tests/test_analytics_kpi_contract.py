"""AI-INTELLIGENCE-014: 'Temel Göstergeler' KPI presentation contract.

The frontend KPI cards need `comparison_category_count`/`comparison_sufficient`
and `metric_summaries` in the API response to build context-aware, Turkish
labeled cards. This is additive transport metadata — `AnalyticsResult`'s
internal fields are untouched, only newly exposed through `AnalyticsSchema`.
"""

from datetime import UTC, datetime

from app.analytics.models import AnalyticsResult, DataShape, MetricSummary
from app.api.v1.endpoints.reports import _map_to_response
from app.application_models.workflow_models import QueryResult as WorkflowQueryResult
from app.application_models.workflow_result import WorkflowResult


def _query_result() -> WorkflowQueryResult:
    return WorkflowQueryResult(
        columns=["SubeAdi", "appointment_count"],
        rows=[{"SubeAdi": "Merkez", "appointment_count": 10}],
        row_count=1,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


def test_comparison_fields_are_exposed_in_analytics_schema():
    analytics = AnalyticsResult(
        analytics_type="comparison",
        data_shape=DataShape.CATEGORICAL,
        metrics={"total": 88, "average": 12.57},
        comparison_category_count=1,
        comparison_sufficient=False,
        comparison_limitation_reason="Seçilen kapsamda yalnızca bir kategori bulundu.",
    )
    result = WorkflowResult(
        question="test", query_result=_query_result(), generated_sql="SELECT 1", analytics=analytics
    )
    response = _map_to_response(result)
    assert response.analytics is not None
    assert response.analytics.comparison_category_count == 1
    assert response.analytics.comparison_sufficient is False
    assert response.analytics.comparison_limitation_reason


def test_metric_summaries_are_exposed_with_labels():
    analytics = AnalyticsResult(
        analytics_type="summary",
        data_shape=DataShape.SINGLE_ROW,
        metric_summaries={
            "monthly_appointment_count": MetricSummary(
                metric_id="monthly_appointment_count",
                metric_label="Aylık Randevu Sayısı",
                total=88.0,
            )
        },
    )
    result = WorkflowResult(
        question="test", query_result=_query_result(), generated_sql="SELECT 1", analytics=analytics
    )
    response = _map_to_response(result)
    assert response.analytics is not None
    summary = response.analytics.metric_summaries["monthly_appointment_count"]
    assert summary["metric_id"] == "monthly_appointment_count"
    assert summary["metric_label"] == "Aylık Randevu Sayısı"
    assert summary["total"] == 88.0


def test_analytics_metrics_dict_keys_remain_canonical_untranslated():
    # Internal analytics keys must never be renamed at the transport layer —
    # only the frontend translates them for display.
    analytics = AnalyticsResult(
        analytics_type="trend",
        data_shape=DataShape.TIME_SERIES,
        metrics={
            "total": 88,
            "average": 12.57,
            "median": 11.0,
            "percentage_change": -46.15,
            "trend_direction": "upward",
        },
    )
    result = WorkflowResult(
        question="test", query_result=_query_result(), generated_sql="SELECT 1", analytics=analytics
    )
    response = _map_to_response(result)
    assert response.analytics is not None
    assert set(response.analytics.metrics.keys()) == {
        "total",
        "average",
        "median",
        "percentage_change",
        "trend_direction",
    }
