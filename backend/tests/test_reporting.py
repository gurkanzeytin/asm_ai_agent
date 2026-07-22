from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.application_models.workflow_models import QueryResult
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.reporting import ReportClassifier, ReportType
from app.services.interfaces import IPromptService
from app.services.report_generator import IReportGenerator
from app.services.report_service import ReportService


def _query_result(columns: list[str], rows: list[dict]) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )


def test_list_intent_selects_table_even_above_threshold():
    classifier = ReportClassifier(analytical_row_threshold=2)
    rows = [{"id": i, "ad_soyad": f"Doktor {i}"} for i in range(45)]

    report_type = classifier.classify(
        _query_result(["id", "ad_soyad"], rows),
        question="Doktorlari listele",
        sql="SELECT * FROM doktorlar",
    )

    assert report_type == ReportType.TABLE


def test_trend_intent_selects_analytical():
    classifier = ReportClassifier(analytical_row_threshold=20)

    report_type = classifier.classify(
        _query_result(
            ["ay", "randevu_sayisi"],
            [{"ay": "Ocak", "randevu_sayisi": 10}, {"ay": "Subat", "randevu_sayisi": 12}],
        ),
        question="Son 6 ayin egilimi",
        sql="SELECT ay, COUNT(*) AS randevu_sayisi FROM randevular GROUP BY ay",
    )

    assert report_type == ReportType.ANALYTICAL


@pytest.mark.asyncio
async def test_summary_query_uses_template():
    prompt_service = AsyncMock(spec=IPromptService)
    llm_provider = AsyncMock(spec=ILLMProvider)
    generator = AsyncMock(spec=IReportGenerator)
    service = ReportService(prompt_service, llm_provider, generator=generator)

    report = await service.generate_report(
        question="Kac doktor var?",
        sql="SELECT COUNT(*) AS doktor_sayisi FROM doktorlar",
        query_result=_query_result(["doktor_sayisi"], [{"doktor_sayisi": 45}]),
    )

    assert report.provider == "template"
    assert report.model == "single_value"
    generator.generate.assert_not_called()
    prompt_service.render_report_prompt.assert_not_called()


@pytest.mark.asyncio
async def test_trend_query_invokes_llm():
    prompt_service = AsyncMock(spec=IPromptService)
    prompt_service.render_report_prompt.return_value = "Rendered trend prompt"
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.get_metadata.return_value = {"provider": "mock-provider"}
    generator = AsyncMock(spec=IReportGenerator)
    generator.generate.return_value = LLMResponse(
        content="# Trend Report\n\nTrend details",
        model="mock-model",
        latency_ms=25.0,
    )
    service = ReportService(prompt_service, llm_provider, generator=generator)

    report = await service.generate_report(
        question="Son 6 ayin egilimi",
        sql="SELECT ay, COUNT(*) AS randevu_sayisi FROM randevular GROUP BY ay",
        query_result=_query_result(
            ["ay", "randevu_sayisi"],
            [{"ay": "Ocak", "randevu_sayisi": 10}, {"ay": "Subat", "randevu_sayisi": 12}],
        ),
    )

    assert report.provider == "mock-provider"
    generator.generate.assert_called_once_with("Rendered trend prompt", llm_provider)
