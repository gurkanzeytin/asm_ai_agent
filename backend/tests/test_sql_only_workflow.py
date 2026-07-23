from datetime import UTC, datetime

import pytest

from app.analytics.models import AnalyticsResult, VisualizationRecommendation, VisualizationType
from app.application_models.generated_sql import GeneratedSQL
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.services.reporting_service import ReportingService
from app.sql_validator import SQLValidationResult

_GROUPED_SQL = (
    "SELECT Brans, COUNT(*) AS appointment_count "
    "FROM dbo.vw_RandevuRaporu GROUP BY Brans;"
)


class CapturingGraph:
    def __init__(self):
        self.initial_state = None

    async def ainvoke(self, initial_state):
        self.initial_state = initial_state
        return {
            "generated_sql": GeneratedSQL(
                sql="SELECT TOP (10) * FROM dbo.vw_RandevuRaporu;",
                validation_result=SQLValidationResult(valid=True),
                provider="test",
                model="test",
                latency_ms=0.0,
            ),
            "errors": [],
            "node_timings": {
                "generate_sql": 1.0,
                "validate_sql": 1.0,
            },
            "response_mode": initial_state.response_mode,
        }


def _query_result() -> QueryResult:
    return QueryResult(
        columns=["department", "appointment_count"],
        rows=[{"department": "Kardiyoloji", "appointment_count": 12}],
        row_count=1,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


class DataOnlyGraph:
    def __init__(self):
        self.initial_state = None

    async def ainvoke(self, initial_state):
        self.initial_state = initial_state
        return {
            "generated_sql": GeneratedSQL(
                sql=_GROUPED_SQL,
                validation_result=SQLValidationResult(valid=True),
                provider="test",
                model="test",
                latency_ms=0.0,
            ),
            "query_result": _query_result(),
            "errors": [],
            "node_timings": {
                "generate_sql": 1.0,
                "validate_sql": 1.0,
                "execute_sql": 1.0,
            },
            "response_mode": initial_state.response_mode,
        }


class VisualizationOnlyGraph:
    def __init__(self):
        self.initial_state = None

    async def ainvoke(self, initial_state):
        self.initial_state = initial_state
        return {
            "generated_sql": GeneratedSQL(
                sql=_GROUPED_SQL,
                validation_result=SQLValidationResult(valid=True),
                provider="test",
                model="test",
                latency_ms=0.0,
            ),
            "query_result": _query_result(),
            "analytics": AnalyticsResult(
                analytics_type="distribution",
                row_count=1,
                visualization=VisualizationRecommendation(
                    type=VisualizationType.BAR_CHART,
                    reason="categorical grouped result",
                ),
            ),
            "errors": [],
            "node_timings": {
                "generate_sql": 1.0,
                "validate_sql": 1.0,
                "execute_sql": 1.0,
                "analyze_results": 1.0,
            },
            "response_mode": initial_state.response_mode,
        }


@pytest.mark.asyncio
async def test_sql_only_workflow_returns_sql_without_query_result_or_safe_error():
    graph = CapturingGraph()
    service = ReportingService(agent_graph=graph)

    result = await service.run_workflow("Sadece SQL sorgusunu ver", session_id=None)

    assert graph.initial_state.response_mode == "sql"
    assert result.outcome == AgentOutcome.SQL_ONLY.value
    assert result.response_mode == "sql"
    assert result.visible_sections == ["sql"]
    assert result.generated_sql == "SELECT TOP (10) * FROM dbo.vw_RandevuRaporu;"
    assert result.query_result is None
    assert result.generated_report is not None
    assert result.generated_report.markdown == (
        "```sql\nSELECT TOP (10) * FROM dbo.vw_RandevuRaporu;\n```"
    )


@pytest.mark.asyncio
async def test_data_only_workflow_returns_table_without_report_generation():
    graph = DataOnlyGraph()
    service = ReportingService(agent_graph=graph)

    result = await service.run_workflow("Branşa göre randevuları listele", session_id=None)

    assert graph.initial_state.response_mode == "data"
    assert result.outcome == AgentOutcome.DATA_ONLY.value
    assert result.response_mode == "data"
    assert result.visible_sections == ["table"]
    assert result.query_result is not None
    assert result.analytics is None
    assert result.generated_report is not None
    assert result.generated_report.model == "data_only_output"


@pytest.mark.asyncio
async def test_visualization_only_workflow_returns_chart_metadata_without_llm_report():
    graph = VisualizationOnlyGraph()
    service = ReportingService(agent_graph=graph)

    result = await service.run_workflow("Branşa göre randevu grafiği çiz", session_id=None)

    assert graph.initial_state.response_mode == "visualization"
    assert result.outcome == AgentOutcome.VISUALIZATION_ONLY.value
    assert result.response_mode == "visualization"
    assert result.visible_sections == ["chart"]
    assert result.query_result is not None
    assert result.analytics is not None
    assert result.analytics.visualization is not None
    assert result.generated_report is not None
    assert result.generated_report.model == "visualization_only_output"
