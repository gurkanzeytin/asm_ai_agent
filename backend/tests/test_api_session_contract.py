"""POST /api/v1/report/ — session_id contract (Part 1 of the chat-memory fix).

An omitted session_id must never resolve to a shared "default" session; the
endpoint must generate a fresh ephemeral one and pass it through to
ReportingService.run_workflow, and the resolved session_id must always be
echoed back in the response.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.deps import get_reporting_service
from app.application_models.workflow_result import WorkflowResult
from app.context.session_store import DEFAULT_SESSION_ID
from app.main import app
from app.services.reporting_service import ReportingService

ENDPOINT = "/api/v1/report/"


def _mock_service(session_id: str) -> tuple[ReportingService, AsyncMock]:
    mock = MagicMock(spec=ReportingService)
    result = WorkflowResult(
        workflow_id="wf-1",
        question="q",
        session_id=session_id,
        follow_up_detected=False,
        context_applied=False,
        memory_updated=True,
        memory_turn_count=1,
    )
    mock.run_workflow = AsyncMock(return_value=result)
    return mock, mock.run_workflow


@pytest.mark.asyncio
async def test_omitted_session_id_never_becomes_literal_default(client: AsyncClient):
    mock_service, run_workflow_mock = _mock_service(session_id="sess-generated")
    app.dependency_overrides[get_reporting_service] = lambda: mock_service
    try:
        await client.post(ENDPOINT, json={"question": "Toplam kaç randevu var?"})
        call_kwargs = run_workflow_mock.call_args.kwargs
        assert call_kwargs["session_id"] != "default"
        assert call_kwargs["session_id"] != DEFAULT_SESSION_ID
        assert call_kwargs["session_id"] is not None
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_two_omitted_requests_get_different_session_ids(client: AsyncClient):
    mock_service, run_workflow_mock = _mock_service(session_id="sess-generated")
    app.dependency_overrides[get_reporting_service] = lambda: mock_service
    try:
        await client.post(ENDPOINT, json={"question": "Toplam kaç randevu var?"})
        first_session = run_workflow_mock.call_args.kwargs["session_id"]
        await client.post(ENDPOINT, json={"question": "Toplam kaç randevu var?"})
        second_session = run_workflow_mock.call_args.kwargs["session_id"]
        assert first_session != second_session
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_explicit_session_id_is_passed_through_unchanged(client: AsyncClient):
    mock_service, run_workflow_mock = _mock_service(session_id="my-explicit-session")
    app.dependency_overrides[get_reporting_service] = lambda: mock_service
    try:
        await client.post(
            ENDPOINT,
            json={"question": "Toplam kaç randevu var?", "session_id": "my-explicit-session"},
        )
        call_kwargs = run_workflow_mock.call_args.kwargs
        assert call_kwargs["session_id"] == "my-explicit-session"
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_resolved_session_id_echoed_in_response(client: AsyncClient):
    mock_service, _ = _mock_service(session_id="my-explicit-session")
    app.dependency_overrides[get_reporting_service] = lambda: mock_service
    try:
        response = await client.post(
            ENDPOINT,
            json={"question": "Toplam kaç randevu var?", "session_id": "my-explicit-session"},
        )
        body = response.json()
        assert body["session_id"] == "my-explicit-session"
        assert body["memory_updated"] is True
        assert body["memory_turn_count"] == 1
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_response_contract_backward_compatible_without_memory_fields(client: AsyncClient):
    """A client that only reads the pre-existing fields is unaffected."""
    mock_service, _ = _mock_service(session_id="s1")
    app.dependency_overrides[get_reporting_service] = lambda: mock_service
    try:
        response = await client.post(ENDPOINT, json={"question": "Toplam kaç randevu var?"})
        body = response.json()
        assert body["success"] is True
        assert "question" in body
        assert "outcome" in body
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)
