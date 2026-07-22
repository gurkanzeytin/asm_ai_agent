from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.application_models.generated_report import GeneratedReport
from app.application_models.workflow_models import QueryResult
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.reporting import ReportClassifier, ReportType, TemplateReportRenderer
from app.services.interfaces import IPromptService
from app.services.report_generator import IReportGenerator
from app.services.report_service import ReportService


def _query_result(
    columns: list[str],
    rows: list[dict],
    row_count: int | None = None,
) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows) if row_count is None else row_count,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )


def test_report_classifier_shapes():
    classifier = ReportClassifier(analytical_row_threshold=2)

    assert classifier.classify(_query_result(["count"], [])) == ReportType.EMPTY
    assert classifier.classify(_query_result(["count"], [{"count": 37}])) == ReportType.SINGLE_VALUE
    assert (
        classifier.classify(
            _query_result(
                ["doctor", "appointments"],
                [{"doctor": "Ahmet", "appointments": 18}],
            )
        )
        == ReportType.SINGLE_ROW
    )
    assert (
        classifier.classify(_query_result(["doctor"], [{"doctor": "A"}, {"doctor": "B"}]))
        == ReportType.TABLE
    )
    assert (
        classifier.classify(
            _query_result(["doctor"], [{"doctor": "A"}, {"doctor": "B"}, {"doctor": "C"}]),
            question="Doktorlari listele",
            sql="SELECT * FROM doktorlar",
        )
        == ReportType.TABLE
    )
    assert (
        classifier.classify(
            _query_result(["month", "count"], [{"month": "Ocak", "count": 10}, {"month": "Subat", "count": 12}]),
            question="Son 6 ayin egilimi nedir?",
            sql="SELECT month, COUNT(*) FROM randevular GROUP BY month",
        )
        == ReportType.ANALYTICAL
    )


def test_template_renderer_single_value():
    rendered = TemplateReportRenderer().render(
        ReportType.SINGLE_VALUE,
        _query_result(["doktor_sayisi"], [{"doktor_sayisi": 37}]),
    )

    assert rendered is not None
    assert rendered.template_name == "single_value"
    assert "37" in rendered.markdown
    assert "Doktor Sayisi" in rendered.markdown


def test_template_renderer_single_row():
    rendered = TemplateReportRenderer().render(
        ReportType.SINGLE_ROW,
        _query_result(["doktor", "randevu"], [{"doktor": "Ahmet Yilmaz", "randevu": 18}]),
    )

    assert rendered is not None
    assert "- **Doktor:** Ahmet Yilmaz" in rendered.markdown
    assert "- **Randevu:** 18" in rendered.markdown


def test_template_renderer_table():
    rendered = TemplateReportRenderer().render(
        ReportType.TABLE,
        _query_result(
            ["doktor", "randevu"],
            [{"doktor": "A", "randevu": 10}, {"doktor": "B", "randevu": 8}],
        ),
    )

    assert rendered is not None
    assert "| Doktor | Randevu |" in rendered.markdown
    assert "| --- | --- |" in rendered.markdown
    assert "| A | 10 |" in rendered.markdown
    assert "| B | 8 |" in rendered.markdown


def test_template_renderer_empty():
    rendered = TemplateReportRenderer().render(ReportType.EMPTY, _query_result(["id"], []))

    assert rendered is not None
    assert rendered.template_name == "empty"
    assert "uygun kayıt bulunamadı" in rendered.markdown


@pytest.mark.asyncio
async def test_report_service_bypasses_llm_for_template_report():
    prompt_service = AsyncMock(spec=IPromptService)
    llm_provider = AsyncMock(spec=ILLMProvider)
    generator = AsyncMock(spec=IReportGenerator)
    service = ReportService(
        prompt_service=prompt_service,
        llm_provider=llm_provider,
        generator=generator,
        classifier=ReportClassifier(analytical_row_threshold=20),
    )

    report = await service.generate_report(
        question="Kac doktor var?",
        sql="SELECT COUNT(*) AS doktor_sayisi FROM doktorlar",
        query_result=_query_result(["doktor_sayisi"], [{"doktor_sayisi": 45}]),
        execution_id="exec-template",
    )

    assert isinstance(report, GeneratedReport)
    assert report.provider == "template"
    assert report.model == "single_value"
    assert "45" in report.markdown
    assert report.execution_id == "exec-template"
    prompt_service.render_report_prompt.assert_not_called()
    generator.generate.assert_not_called()


@pytest.mark.asyncio
async def test_report_service_routes_analytical_result_to_llm():
    prompt_service = AsyncMock(spec=IPromptService)
    prompt_service.render_report_prompt.return_value = "Rendered analytical prompt"
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.get_metadata.return_value = {"provider": "mock-provider"}
    generator = AsyncMock(spec=IReportGenerator)
    generator.generate.return_value = LLMResponse(
        content="# Analitik Rapor\n\nEğilim özeti",
        model="mock-model",
        latency_ms=25.0,
        prompt_tokens=10,
        completion_tokens=20,
    )
    service = ReportService(
        prompt_service=prompt_service,
        llm_provider=llm_provider,
        generator=generator,
        classifier=ReportClassifier(analytical_row_threshold=2),
    )
    result = _query_result(
        ["bolum", "randevu"],
        [{"bolum": "A", "randevu": 10}, {"bolum": "B", "randevu": 8}, {"bolum": "C", "randevu": 7}],
    )

    report = await service.generate_report(
        question="Son 6 ayin bolum bazinda randevu egilimlerini analiz et.",
        sql="SELECT bolum, randevu FROM trend",
        query_result=result,
        execution_id="exec-analytical",
    )

    assert report.provider == "mock-provider"
    assert report.model == "mock-model"
    assert report.title == "Analitik Rapor"
    prompt_service.render_report_prompt.assert_called_once()
    generator.generate.assert_called_once_with("Rendered analytical prompt", llm_provider)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "sql", "columns"),
    [
        ("Doktorlari listele", "SELECT * FROM doktorlar", ["id", "ad_soyad"]),
        ("Hastalari listele", "SELECT * FROM hastalar", ["id", "ad_soyad"]),
        ("Randevulari listele", "SELECT * FROM randevular", ["id", "randevu_tarihi"]),
        ("Ilaclari listele", "SELECT * FROM ilaclar", ["id", "ilac_adi"]),
        ("Sigorta sirketlerini listele", "SELECT * FROM sigorta_sirketleri", ["id", "ad"]),
        ("Laboratuvar kayitlarini listele", "SELECT * FROM laboratuvar_testleri", ["id", "test_adi"]),
    ],
)
async def test_report_service_bypasses_llm_for_large_list_queries(question, sql, columns):
    prompt_service = AsyncMock(spec=IPromptService)
    llm_provider = AsyncMock(spec=ILLMProvider)
    generator = AsyncMock(spec=IReportGenerator)
    service = ReportService(
        prompt_service=prompt_service,
        llm_provider=llm_provider,
        generator=generator,
        classifier=ReportClassifier(analytical_row_threshold=2),
    )
    rows = [{columns[0]: i, columns[1]: f"value-{i}"} for i in range(45)]

    report = await service.generate_report(
        question=question,
        sql=sql,
        query_result=_query_result(columns, rows),
        execution_id="exec-list",
    )

    assert report.provider == "template"
    assert report.model == "table"
    assert "Toplam 45 kayıt listelenmiştir." in report.markdown
    prompt_service.render_report_prompt.assert_not_called()
    generator.generate.assert_not_called()


def test_report_classifier_logs_decision(caplog):
    classifier = ReportClassifier(analytical_row_threshold=2)

    with caplog.at_level("INFO"):
        report_type = classifier.classify(
            _query_result(["id"], [{"id": 1}, {"id": 2}, {"id": 3}]),
            question="Doktorlari listele",
            sql="SELECT * FROM doktorlar",
        )

    assert report_type == ReportType.TABLE
    record = next(rec for rec in caplog.records if "REPORT CLASSIFIER" in rec.message)
    assert record.intent == "LIST"
    assert record.report_type == "table"
    assert record.llm_invoked is False
