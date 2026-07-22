"""Focused regression coverage for the result-size safety boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.nodes.generate_report import GenerateReportNode
from app.agent.state import AgentState
from app.api.v1.endpoints.reports import _map_to_response
from app.application_models.workflow_models import QueryResult
from app.application_models.workflow_result import WorkflowResult
from app.planning.models import QueryPlan
from app.reporting.report_classifier import ReportType
from app.reporting.template_renderer import TemplateReportRenderer
from app.services.execution_service import ExecutionService
from app.services.prompt_service import PromptService
from app.services.result_safety import (
    api_result_window,
    is_unsafe_analytical_detail,
    llm_safe_rows,
    result_notice,
)
from app.shared.result_limits import (
    DEFAULT_GROUPED_RESULT_LIMIT,
    DEFAULT_TABLE_PAGE_SIZE,
    MAX_API_ROWS,
    MAX_DATABASE_FETCH_ROWS,
    MAX_UI_ROWS_PER_PAGE,
    OVERSIZED_ANALYTICAL_RESULT_MESSAGE,
)


def _query_result(
    rows: list[dict[str, object]],
    *,
    columns: list[str] | None = None,
    **updates: object,
) -> QueryResult:
    values: dict[str, object] = {
        "columns": columns or (list(rows[0]) if rows else []),
        "rows": rows,
        "row_count": len(rows),
        "execution_time_ms": 1.0,
        "success": True,
        "executed_at": datetime.now(UTC),
        "database_provider": "mssql",
    }
    values.update(updates)
    return QueryResult(**values)


def test_required_limits_are_meeting_safe() -> None:
    assert DEFAULT_TABLE_PAGE_SIZE == 100
    assert MAX_UI_ROWS_PER_PAGE == 100
    assert MAX_API_ROWS == 500
    assert MAX_DATABASE_FETCH_ROWS == 1000
    assert DEFAULT_GROUPED_RESULT_LIMIT == 100


@pytest.mark.asyncio
async def test_execution_stops_after_1001_rows_and_marks_more() -> None:
    repository = MagicMock()
    repository.execute_readonly_query = AsyncMock(
        return_value=[{"value": index} for index in range(1001)]
    )
    validator = MagicMock()
    validator.validate.return_value = MagicMock(valid=True, reason=None)

    result = await ExecutionService(repository, validator).execute_sql("SELECT value FROM safe")

    assert len(result.rows) == 1000
    assert result.returned_row_count == 1000
    assert result.displayed_row_count == 100
    assert result.applied_limit == 1000
    assert result.result_truncated is True
    assert result.has_more is True
    assert result.total_count is None


def test_api_serializes_at_most_500_rows() -> None:
    query_result = _query_result(
        [{"category": index} for index in range(1000)],
        result_truncated=True,
        has_more=True,
        applied_limit=1000,
    )

    response = _map_to_response(WorkflowResult(question="listele", query_result=query_result))

    assert response.query_result is not None
    assert len(response.query_result.rows) == 500
    assert response.query_result.returned_row_count == 500
    assert response.query_result.displayed_row_count == 100
    assert response.query_result.result_truncated is True
    assert response.query_result.has_more is True


def test_oversized_identifier_analytical_result_is_classified_unsafe() -> None:
    result = _query_result(
        [{"HastaId": index, "metric": index} for index in range(1000)],
        has_more=True,
        result_truncated=True,
    )
    plan = QueryPlan(question="özet", analysis_type="summary", metrics=["appointment_count"])

    assert is_unsafe_analytical_detail(result, plan) is True


def test_unsafe_analytical_detail_is_not_forwarded_to_api() -> None:
    result = _query_result(
        [{"HastaId": index, "metric": index} for index in range(1000)],
        has_more=True,
        result_truncated=True,
        unsafe_detail_output=True,
    )

    window = api_result_window(result)

    assert window.rows == []
    assert window.returned_row_count == 0
    assert window.result_truncated is True
    assert window.has_more is True


@pytest.mark.asyncio
async def test_oversized_analytical_guard_returns_exact_safe_message_without_llm() -> None:
    workflow_service = MagicMock()
    workflow_service.execute_report_generation = AsyncMock()
    state = AgentState(
        question="özet",
        analytics_blocked_reason=OVERSIZED_ANALYTICAL_RESULT_MESSAGE,
    )

    result = await GenerateReportNode(workflow_service).execute(state)

    assert result.generated_report is not None
    assert OVERSIZED_ANALYTICAL_RESULT_MESSAGE in result.generated_report.markdown
    assert result.generated_report.provider == "deterministic"
    assert result.outcome == "SAFE_ERROR"
    workflow_service.execute_report_generation.assert_not_awaited()


def test_grouped_42_row_result_remains_fully_available() -> None:
    result = _query_result(
        [{"GenelRandevuBolumAdi": f"Bölüm {index}", "count": index} for index in range(42)],
        result_group_count=42,
    )

    window = api_result_window(result)
    rendered = TemplateReportRenderer().render(ReportType.TABLE, result)

    assert len(window.rows) == 42
    assert window.result_truncated is False
    assert rendered is not None
    assert "42 bölüm listelenmiştir." in rendered.markdown.casefold()


def test_scalar_result_is_unaffected_and_has_no_pagination_notice() -> None:
    result = _query_result([{"appointment_count": 12480}])

    rendered = TemplateReportRenderer().render(ReportType.SINGLE_VALUE, result)

    assert rendered is not None
    assert "12.480" in rendered.markdown
    assert "ilk" not in rendered.markdown.casefold()


def test_known_source_count_is_never_described_as_listed_rows() -> None:
    result = _query_result(
        [{"appointment": index} for index in range(100)],
        source_record_count=552240,
        total_count=552240,
        result_truncated=True,
        has_more=True,
    )

    notice = result_notice(result)

    assert notice == "Toplam 552.240 sonuç bulundu; ilk 100 sonuç gösteriliyor."
    assert "552.240 kayıt listelenmiştir" not in notice


def test_unknown_total_uses_has_more_wording() -> None:
    result = _query_result(
        [{"appointment": index} for index in range(100)],
        result_truncated=True,
        has_more=True,
    )

    assert result_notice(result) == (
        "İlk 100 sonuç gösteriliyor. Daha fazla sonuç bulunmaktadır."
    )


def test_llm_summary_has_at_most_top_and_bottom_ten_rows() -> None:
    result = _query_result(
        [{"category": f"C{index}", "metric": index} for index in range(1000)]
    )

    rows = llm_safe_rows(result)

    assert len(rows) == 20
    assert rows[:10] == result.rows[:10]
    assert rows[-10:] == result.rows[-10:]


def test_llm_summary_omits_identifier_and_pii_values() -> None:
    result = _query_result([{"HastaId": index, "metric": index} for index in range(1000)])

    rows = llm_safe_rows(result)
    assert len(rows) == 20
    assert rows == [{"metric": index} for index in [*range(10), *range(990, 1000)]]


@pytest.mark.asyncio
async def test_report_prompt_contains_only_safe_summary_rows() -> None:
    service = PromptService(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    service.render_prompt = AsyncMock(side_effect=["system", "report"])
    result = _query_result(
        [{"category": f"C{index}", "metric": index} for index in range(1000)],
        result_truncated=True,
        has_more=True,
    )

    await service.render_report_prompt("soru", "SELECT safe", result)

    report_variables = service.render_prompt.await_args_list[1].args[2]
    payload = json.loads(report_variables["results"])
    assert len(payload["rows"]) == 20
    assert payload["rows"][:10] == result.rows[:10]
    assert payload["rows"][-10:] == result.rows[-10:]
    assert payload["result_truncated"] is True
    assert payload["has_more"] is True
    assert payload["result_shape"] == "bounded_tabular_rows"
