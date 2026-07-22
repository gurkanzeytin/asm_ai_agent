import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.deps import get_reporting_service
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.application_models.workflow_result import WorkflowResult
from app.main import app
from app.services.reporting_service import ReportingService
from app.services.workflow_progress import (
    reset_progress_callback,
    set_progress_callback,
    with_progress,
)
from tests.test_api_report import _make_workflow_result


def _terminal_events(response):
    events = [json.loads(line) for line in response.text.splitlines()]
    return events, [event for event in events if event["type"] in {"complete", "error"}]


def _zero_result(session_id: str) -> WorkflowResult:
    return WorkflowResult(
        workflow_id="wf-empty-turn-2",
        question="Sadece gerçekleşenleri göster.",
        generated_sql=(
            "SELECT DoktorId AS DoktorId, COUNT(*) AS appointment_count "
            "FROM dbo.vw_RandevuRaporu "
            "WHERE RandevuDurumu = N'Gerçekleşti' "
            "GROUP BY DoktorId ORDER BY appointment_count DESC;"
        ),
        query_result=QueryResult(
            columns=[],
            rows=[],
            row_count=0,
            execution_time_ms=1,
            success=True,
            executed_at=datetime.now(UTC),
            database_provider="mssql",
        ),
        generated_report=GeneratedReport(
            title="Sonuç Bulunamadı",
            markdown="# Sonuç Bulunamadı\n\nBelirtilen kriterlere uygun kayıt bulunamadı.",
            provider="template",
            model="empty",
            latency_ms=0,
        ),
        outcome=AgentOutcome.NO_RESULT_GUIDANCE.value,
        session_id=session_id,
    )


@pytest.mark.asyncio
async def test_progress_wrapper_emits_before_node_execution():
    events: list[str] = []

    async def callback(stage: str) -> None:
        events.append(stage)

    async def node(state):
        events.append("node")
        return state

    token = set_progress_callback(callback)
    try:
        result = await with_progress("executing_sql", node)({"ok": True})
    finally:
        reset_progress_callback(token)

    assert result == {"ok": True}
    assert events == ["executing_sql", "node"]


@pytest.mark.asyncio
async def test_stream_endpoint_returns_progress_and_complete(client):
    service = MagicMock(spec=ReportingService)

    async def run_workflow(question, session_id, progress_callback):
        assert question == "Bugünkü randevuları göster"
        assert session_id
        await progress_callback("understanding")
        await progress_callback("executing_sql")
        return _make_workflow_result()

    service.run_workflow = AsyncMock(side_effect=run_workflow)
    app.dependency_overrides[get_reporting_service] = lambda: service
    try:
        response = await client.post(
            "/api/v1/report/stream",
            json={"question": "Bugünkü randevuları göster"},
        )
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["progress", "progress", "complete"]
    assert events[0]["stage"] == "understanding"
    assert events[-1]["data"]["success"] is True


@pytest.mark.asyncio
async def test_same_session_stream_delivers_zero_result_as_one_complete_event(client):
    """Endpoint regression for the exact live two-turn delivery contract."""
    session_id = "same-stream-session"
    questions = [
        "2026 Ocak ayında doktorların randevu sayılarını ver.",
        "Sadece gerçekleşenleri göster.",
    ]
    service = MagicMock(spec=ReportingService)
    calls = 0

    async def run_workflow(question, session_id: str, progress_callback):
        nonlocal calls
        assert session_id == "same-stream-session"
        assert question == questions[calls]
        await progress_callback("understanding")
        calls += 1
        if calls == 1:
            return _make_workflow_result().model_copy(
                update={"session_id": session_id, "outcome": AgentOutcome.EXECUTE_SQL.value}
            )
        return _zero_result(session_id)

    service.run_workflow = AsyncMock(side_effect=run_workflow)
    app.dependency_overrides[get_reporting_service] = lambda: service
    try:
        first = await client.post(
            "/api/v1/report/stream",
            json={"question": questions[0], "session_id": session_id},
        )
        second = await client.post(
            "/api/v1/report/stream",
            json={"question": questions[1], "session_id": session_id},
        )
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)

    assert first.status_code == second.status_code == 200
    first_events, first_terminal = _terminal_events(first)
    second_events, second_terminal = _terminal_events(second)
    assert first_events[-1]["type"] == "complete"
    assert len(first_terminal) == 1
    assert second_events[-1]["type"] == "complete"
    assert len(second_terminal) == 1
    payload = second_terminal[0]["data"]
    assert payload["outcome"] == AgentOutcome.NO_RESULT_GUIDANCE.value
    assert payload["query_result"]["row_count"] == 0
    assert payload["report"]["markdown"].strip()
    assert "kayıt bulunamadı" in payload["report"]["markdown"]
    assert service.run_workflow.await_count == 2


@pytest.mark.asyncio
async def test_stream_endpoint_emits_safe_error_as_complete(client):
    result = _make_workflow_result(errors=["controlled failure"]).model_copy(
        update={"outcome": AgentOutcome.SAFE_ERROR.value}
    )
    service = MagicMock(spec=ReportingService)
    service.run_workflow = AsyncMock(return_value=result)
    app.dependency_overrides[get_reporting_service] = lambda: service
    try:
        response = await client.post(
            "/api/v1/report/stream", json={"question": "Soru", "session_id": "safe"}
        )
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)

    _, terminal = _terminal_events(response)
    assert len(terminal) == 1
    assert terminal[0]["type"] == "complete"
    assert terminal[0]["data"]["outcome"] == AgentOutcome.SAFE_ERROR.value
    assert terminal[0]["data"]["report"]["markdown"].strip()


@pytest.mark.asyncio
async def test_stream_endpoint_emits_one_error_when_workflow_raises(client):
    service = MagicMock(spec=ReportingService)
    service.run_workflow = AsyncMock(side_effect=RuntimeError("escaped workflow failure"))
    app.dependency_overrides[get_reporting_service] = lambda: service
    try:
        response = await client.post(
            "/api/v1/report/stream", json={"question": "Soru", "session_id": "error"}
        )
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)

    events, terminal = _terminal_events(response)
    assert events[-1]["type"] == "error"
    assert len(terminal) == 1
    assert terminal[0]["error_code"] == "INTERNAL_ERROR"
