"""Tests for POST /api/v1/report endpoint.

Covers:
- Successful request → HTTP 200 with full schema
- Missing / empty question → HTTP 422 (Pydantic validation)
- QueryExecutionException → HTTP 400
- SQLSafetyViolation → HTTP 400
- SQLServiceException → HTTP 400
- ReportServiceException → HTTP 502
- WorkflowServiceException → HTTP 500
- Response schema shape validation
- Dependency injection resolution
- OpenAPI schema generation
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.api.deps import get_reporting_service
from app.application_models.generated_report import GeneratedReport
from app.application_models.workflow_metrics import WorkflowMetrics
from app.application_models.workflow_models import QueryResult
from app.application_models.workflow_result import WorkflowResult
from app.main import app
from app.services.exceptions import (
    QueryExecutionException,
    ReportServiceException,
    SQLServiceException,
    WorkflowServiceException,
)
from app.services.reporting_service import ReportingService
from app.shared.exceptions import SQLSafetyViolation

ENDPOINT = "/api/v1/report/"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _make_workflow_result(errors: list | None = None) -> WorkflowResult:
    """Builds a fully populated WorkflowResult for success-path tests."""
    report = GeneratedReport(
        title="Doctor Appointment Report",
        markdown="# Doctor Appointment Report\n\n## Key Findings\nTekbay Aksu: 155 appointments.",
        provider="ollama",
        model="qwen3:8b",
        latency_ms=210.0,
        prompt_tokens=350,
        completion_tokens=180,
        generated_at=datetime.now(UTC),
        execution_id="wf-test-001",
    )
    qr = QueryResult(
        columns=["ad_soyad", "randevu_sayisi"],
        rows=[{"ad_soyad": "Tekbay Aksu", "randevu_sayisi": 155}],
        row_count=1,
        execution_time_ms=12.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )
    return WorkflowResult(
        workflow_id="wf-test-001",
        question="Which doctor has the highest number of appointments?",
        generated_sql=(
            "SELECT d.ad_soyad, COUNT(r.id) AS randevu_sayisi "
            "FROM doktorlar d JOIN randevular r ON d.id = r.doktor_id "
            "GROUP BY d.ad_soyad ORDER BY randevu_sayisi DESC LIMIT 1;"
        ),
        query_result=qr,
        generated_report=report,
        metrics=WorkflowMetrics(
            execute_sql_ms=12.0,
            generate_report_ms=210.0,
            total_ms=4321.0,
        ),
        errors=errors or [],
    )


def _mock_reporting_service(return_value=None, side_effect=None) -> ReportingService:
    """Creates a mocked ReportingService for dependency override."""
    mock = MagicMock(spec=ReportingService)
    if side_effect:
        mock.run_workflow = AsyncMock(side_effect=side_effect)
    else:
        mock.run_workflow = AsyncMock(return_value=return_value)
    return mock


# ─────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_report_success(client: AsyncClient):
    """POST /api/v1/report/ returns HTTP 200 with full nested response schema."""
    mock_service = _mock_reporting_service(return_value=_make_workflow_result())
    app.dependency_overrides[get_reporting_service] = lambda: mock_service

    try:
        response = await client.post(
            ENDPOINT,
            json={"question": "Which doctor has the highest number of appointments?"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["workflow_id"] == "wf-test-001"
        assert data["question"] == "Which doctor has the highest number of appointments?"
        assert "SELECT" in data["generated_sql"]

        qr = data["query_result"]
        assert qr["columns"] == ["ad_soyad", "randevu_sayisi"]
        assert qr["row_count"] == 1
        assert qr["rows"][0]["ad_soyad"] == "Tekbay Aksu"

        rpt = data["report"]
        assert rpt["title"] == "Doctor Appointment Report"
        assert "Tekbay Aksu" in rpt["markdown"]

        meta = data["metadata"]
        assert meta["provider"] == "ollama"
        assert meta["model"] == "qwen3:8b"
        assert meta["latency_ms"] == 210.0
        assert meta["prompt_tokens"] == 350
        assert meta["completion_tokens"] == 180

        timing = data["timing"]
        assert timing["execute_sql_ms"] == 12.0
        assert timing["generate_report_ms"] == 210.0
        assert timing["total_ms"] == 4321.0
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_report_output_contract_exposes_requested_sections(client: AsyncClient):
    """The API must expose the backend output policy unchanged for the UI router."""
    result = _make_workflow_result()
    result.response_mode = "sql"
    result.visible_sections = ["sql"]
    result.generated_sql = (
        "SELECT COUNT(*) AS appointment_count "
        "FROM dbo.vw_RandevuRaporu "
        "WHERE CAST([RandevuBaslangicTarihi] AS date) = CAST(GETDATE() AS date);"
    )
    result.generated_report = result.generated_report.model_copy(
        update={"markdown": "This narrative must not drive SQL-only UI output."}
    )

    mock_service = _mock_reporting_service(return_value=result)
    app.dependency_overrides[get_reporting_service] = lambda: mock_service

    try:
        response = await client.post(
            ENDPOINT,
            json={"question": "Bugunku randevu sayisi icin sadece SQL sorgusunu ver"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["response_mode"] == "sql"
        assert data["visible_sections"] == ["sql"]
        assert data["generated_sql"] == result.generated_sql
        assert "```" not in data["generated_sql"]
        assert data["report"]["markdown"] == result.generated_report.markdown
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_report_missing_question(client: AsyncClient):
    """POST with empty body returns HTTP 422 from Pydantic validation."""
    response = await client.post(ENDPOINT, json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_report_empty_question(client: AsyncClient):
    """POST with blank question (below min_length) returns HTTP 422."""
    response = await client.post(ENDPOINT, json={"question": "  "})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_report_query_execution_failure(client: AsyncClient):
    """QueryExecutionException raised by ReportingService → HTTP 400."""
    mock_service = _mock_reporting_service(side_effect=QueryExecutionException("DB failure"))
    app.dependency_overrides[get_reporting_service] = lambda: mock_service

    try:
        response = await client.post(ENDPOINT, json={"question": "How many patients?"})
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "QUERY_EXECUTION_ERROR"
        assert "stack" not in str(data)
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_report_sql_validation_failure(client: AsyncClient):
    """SQLSafetyViolation raised by ReportingService → HTTP 400."""
    mock_service = _mock_reporting_service(side_effect=SQLSafetyViolation("DROP TABLE detected"))
    app.dependency_overrides[get_reporting_service] = lambda: mock_service

    try:
        response = await client.post(ENDPOINT, json={"question": "How many patients?"})
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "SQL_VALIDATION_ERROR"
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_report_sql_generation_failure(client: AsyncClient):
    """SQLServiceException raised by ReportingService → HTTP 400."""
    mock_service = _mock_reporting_service(
        side_effect=SQLServiceException("LLM returned invalid SQL")
    )
    app.dependency_overrides[get_reporting_service] = lambda: mock_service

    try:
        response = await client.post(ENDPOINT, json={"question": "How many patients?"})
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "SQL_GENERATION_ERROR"
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_report_llm_failure(client: AsyncClient):
    """ReportServiceException raised by ReportingService → HTTP 502."""
    mock_service = _mock_reporting_service(side_effect=ReportServiceException("Ollama timeout"))
    app.dependency_overrides[get_reporting_service] = lambda: mock_service

    try:
        response = await client.post(ENDPOINT, json={"question": "How many patients?"})
        assert response.status_code == 502
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "LLM_ERROR"
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_report_workflow_failure(client: AsyncClient):
    """WorkflowServiceException raised by ReportingService → HTTP 500."""
    mock_service = _mock_reporting_service(side_effect=WorkflowServiceException("Node failed"))
    app.dependency_overrides[get_reporting_service] = lambda: mock_service

    try:
        response = await client.post(ENDPOINT, json={"question": "How many patients?"})
        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False
        assert data["error_code"] == "WORKFLOW_ERROR"
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_response_schema_shape(client: AsyncClient):
    """Verifies the response contains all required top-level fields."""
    mock_service = _mock_reporting_service(return_value=_make_workflow_result())
    app.dependency_overrides[get_reporting_service] = lambda: mock_service

    try:
        response = await client.post(
            ENDPOINT, json={"question": "Which doctor has the highest number of appointments?"}
        )
        assert response.status_code == 200
        data = response.json()
        expected_fields = (
            "success",
            "workflow_id",
            "question",
            "generated_sql",
            "query_result",
            "report",
            "metadata",
        )
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
        for field in ("columns", "rows", "row_count"):
            assert field in data["query_result"], f"Missing query_result field: {field}"
        for field in ("title", "markdown"):
            assert field in data["report"], f"Missing report field: {field}"
        for field in ("provider", "model", "latency_ms"):
            assert field in data["metadata"], f"Missing metadata field: {field}"
    finally:
        app.dependency_overrides.pop(get_reporting_service, None)


@pytest.mark.asyncio
async def test_dependency_injection(client: AsyncClient):
    """Verifies get_reporting_service() resolves to the container singleton."""
    from app.bootstrap import container

    service = get_reporting_service()
    assert service is container.reporting_service
    assert isinstance(service, ReportingService)


@pytest.mark.asyncio
async def test_openapi_schema_generated(client: AsyncClient):
    """Verifies OpenAPI JSON schema is generated and contains the /api/v1/report path."""
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema.get("paths", {})
    assert "/api/v1/report/" in paths, (
        f"Expected /api/v1/report/ in OpenAPI paths, got: {list(paths.keys())}"
    )
    post_op = paths["/api/v1/report/"]["post"]
    assert post_op["summary"] == "Generate an AI analytical report"
