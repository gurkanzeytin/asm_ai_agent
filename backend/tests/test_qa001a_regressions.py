"""Regression tests for QA-001A — comparison & trend query reliability.

Covers the four failure mechanisms found in the investigation:
1. Trend/period-analysis questions generating raw-row SQL instead of monthly
   aggregation (SQLService deterministic repair trigger).
2. Bare period-analysis questions ("Son 6 ayı analiz et") losing the appointment
   subject before retrieval (QueryAnalyzer expansion rule).
3. Ollama read-timeout retry storm (~124s of guaranteed-futile retries).
4. Report LLM failure surfacing as a generic workflow error instead of
   degrading to a deterministic template report.
5. Analytics computing trend metrics over id-like columns.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.analytics.analytics_engine import AnalyticsEngine
from app.application_models.workflow_models import QueryResult
from app.llm.exceptions import LLMTimeoutError
from app.llm.interfaces import ILLMProvider
from app.llm.ollama import OllamaProvider
from app.llm.schemas import LLMResponse
from app.parsers.output_parser import OutputParser
from app.services.query_analyzer import QueryAnalyzer
from app.services.report_service import ReportService
from app.services.sql_service import SQLService
from app.sql_validator.validator import SQLValidator


def _query_result(columns, rows) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime(2026, 7, 14, 12, 0, 0),
        database_provider="mssql",
    )


TREND_QUESTION = (
    "2026-01-14 ile 2026-07-14 tarihleri arasinda randevulari analiz et"
)

RAW_ROW_SQL = (
    "SELECT randevular.id AS randevu_id, hasta_id, doktor_id, bolum_id, "
    "randevu_tarihi, durum FROM randevular "
    "WHERE randevu_tarihi BETWEEN '2026-01-14' AND '2026-07-14';"
)

AGGREGATED_SQL = (
    "SELECT strftime('%Y-%m', randevu_tarihi) AS ay, COUNT(*) AS adet "
    "FROM randevular WHERE randevu_tarihi BETWEEN '2026-01-14' AND '2026-07-14' "
    "GROUP BY ay ORDER BY ay;"
)


# ── 1. SQLService: trend questions must aggregate ─────────────────────────────


@pytest.mark.asyncio
async def test_trend_question_with_raw_row_sql_triggers_aggregation_repair():
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.generate.side_effect = [
        LLMResponse(content=RAW_ROW_SQL, model="mock", latency_ms=1.0),
        LLMResponse(content=AGGREGATED_SQL, model="mock", latency_ms=1.0),
    ]
    llm_provider.get_metadata.return_value = {"provider": "mock-provider"}
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql("prompt", question=TREND_QUESTION)

    assert llm_provider.generate.call_count == 2
    repair_prompt = llm_provider.generate.call_args_list[1].args[0]
    assert "monthly aggregation" in repair_prompt
    assert "group by" in generated.sql.lower()
    assert "strftime" in generated.sql.lower()


@pytest.mark.asyncio
async def test_trend_question_with_aggregated_sql_needs_no_repair():
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.generate.return_value = LLMResponse(
        content=AGGREGATED_SQL, model="mock", latency_ms=1.0
    )
    llm_provider.get_metadata.return_value = {"provider": "mock-provider"}
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql("prompt", question=TREND_QUESTION)

    assert llm_provider.generate.call_count == 1
    assert "group by" in generated.sql.lower()


@pytest.mark.asyncio
async def test_comparison_question_without_group_by_is_not_flagged_as_trend():
    comparison_sql = (
        "SELECT bolum_adi, COUNT(*) AS randevu_sayisi FROM randevular "
        "JOIN bolumler ON randevular.bolum_id = bolumler.id "
        "WHERE bolum_adi IN ('Kardiyoloji', 'Psikiyatri') GROUP BY bolum_adi;"
    )
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.generate.return_value = LLMResponse(
        content=comparison_sql, model="mock", latency_ms=1.0
    )
    llm_provider.get_metadata.return_value = {"provider": "mock-provider"}
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql(
        "prompt", question="kardiyoloji ile psikiyatri yi karsilastir"
    )

    assert llm_provider.generate.call_count == 1
    assert generated.validation_result.valid is True


@pytest.mark.asyncio
async def test_truncated_sql_output_triggers_simplification_repair():
    truncated_sql = (
        "SELECT strftime('%Y-%m', randevu_tarihi) AS ay, COUNT(*) AS adet "
        "FROM randevular LEFT JOIN test_sonuclari ON randevular.id = test_son"
    )
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.generate.side_effect = [
        LLMResponse(
            content=truncated_sql, model="mock", latency_ms=1.0, finish_reason="max_tokens"
        ),
        LLMResponse(content=AGGREGATED_SQL, model="mock", latency_ms=1.0, finish_reason="stop"),
    ]
    llm_provider.get_metadata.return_value = {"provider": "mock-provider"}
    service = SQLService(llm_provider, OutputParser(), SQLValidator())

    generated = await service.generate_sql("prompt", question=TREND_QUESTION)

    assert llm_provider.generate.call_count == 2
    repair_prompt = llm_provider.generate.call_args_list[1].args[0]
    assert "cut off" in repair_prompt
    assert "group by" in generated.sql.lower()
    # SQL generation must request enough tokens that aggregation queries survive.
    for call in llm_provider.generate.call_args_list:
        assert call.kwargs["options"]["num_predict"] >= 400


def test_trend_aggregation_issue_detection_matrix():
    service = SQLService(AsyncMock(spec=ILLMProvider), OutputParser(), SQLValidator())

    # Trend question + raw-row SQL → flagged
    assert service._trend_aggregation_issue(TREND_QUESTION, RAW_ROW_SQL) is not None
    # Trend question + aggregated SQL → clean
    assert service._trend_aggregation_issue(TREND_QUESTION, AGGREGATED_SQL) is None
    # Analysis marker without a date range → not a period analysis
    assert service._trend_aggregation_issue("randevulari analiz et", RAW_ROW_SQL) is None
    # No analysis marker → clean
    assert (
        service._trend_aggregation_issue(
            "2026-01-14 ile 2026-07-14 tarihleri arasinda randevulari listele",
            RAW_ROW_SQL,
        )
        is None
    )


# ── 2. QueryAnalyzer: bare period analysis gets an appointment subject ────────


def test_bare_period_analysis_expands_to_appointment_subject():
    analyzer = QueryAnalyzer()

    analysis = analyzer.analyze(
        "Son 6 ayı analiz et ve dikkat edilmesi gereken noktaları söyle."
    )

    assert "randevu" in analysis.final_query
    assert "tarihleri arasinda" in analysis.final_query
    assert any(entity.entity_type == "Appointment" for entity in analysis.entities)


def test_period_analysis_with_explicit_subject_is_not_double_expanded():
    analyzer = QueryAnalyzer()

    analysis = analyzer.analyze("Son 6 ayın randevularını analiz et.")

    assert analysis.final_query.count("randevu") == 1
    assert "tarihleri arasinda" in analysis.final_query


# ── 3. Ollama: read timeouts fail fast instead of retrying ────────────────────


@pytest.mark.asyncio
async def test_read_timeout_is_not_retried():
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", retry_count=3
    )

    with patch.object(provider._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ReadTimeout("model too slow")

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMTimeoutError):
                await provider.generate("Trend report prompt")

        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()

    await provider.close()


@pytest.mark.asyncio
async def test_connect_errors_are_still_retried():
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", retry_count=1
    )

    mock_success = MagicMock()
    mock_success.status_code = 200
    mock_success.json.return_value = {"response": "ok", "prompt_eval_count": 1, "eval_count": 1}

    with patch.object(provider._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [httpx.ConnectError("refused"), mock_success]
        with patch("asyncio.sleep", new_callable=AsyncMock):
            response = await provider.generate("prompt")

    assert response.content == "ok"
    await provider.close()


# ── 4. ReportService: LLM failure degrades to a template report ───────────────


def _appointment_rows(count: int) -> list[dict]:
    return [
        {
            "randevu_id": index,
            "randevu_tarihi": "2026-01-14",
            "durum": "tamamlandi",
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_report_llm_timeout_falls_back_to_template_table():
    prompt_service = AsyncMock()
    prompt_service.render_report_prompt.return_value = "prompt"
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.generate.side_effect = LLMTimeoutError("read timeout")
    llm_provider.get_metadata.return_value = {"provider": "ollama"}

    service = ReportService(prompt_service=prompt_service, llm_provider=llm_provider)
    query_result = _query_result(
        ["randevu_id", "randevu_tarihi", "durum"], _appointment_rows(250)
    )

    report = await service.generate_report(
        question="Son 6 ayın randevularını analiz et",
        sql=RAW_ROW_SQL,
        query_result=query_result,
    )

    assert report.provider == "template"
    assert report.model == "fallback_table"
    assert report.markdown
    # Fallback table is capped at REPORT_MAX_ROWS data rows.
    data_rows = [
        line for line in report.markdown.splitlines() if line.startswith("| ")
    ]
    from app.core.config import settings

    max_rows = getattr(settings, "REPORT_MAX_ROWS", 100)
    assert len(data_rows) <= max_rows + 2  # header + separator + capped rows


@pytest.mark.asyncio
async def test_report_llm_success_path_is_unchanged():
    prompt_service = AsyncMock()
    prompt_service.render_report_prompt.return_value = "prompt"
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.generate.return_value = LLMResponse(
        content="# Rapor\n\nMetin.", model="mock", latency_ms=5.0
    )
    llm_provider.get_metadata.return_value = {"provider": "ollama"}

    service = ReportService(prompt_service=prompt_service, llm_provider=llm_provider)
    query_result = _query_result(
        ["ay", "randevu_sayisi"],
        [{"ay": "2026-01", "randevu_sayisi": 201}, {"ay": "2026-02", "randevu_sayisi": 240}],
    )

    report = await service.generate_report(
        question="Son 6 ayın randevularını analiz et",
        sql=AGGREGATED_SQL,
        query_result=query_result,
    )

    assert report.provider == "ollama"
    assert report.title == "Rapor"


# ── 5. Analytics: never compute metrics over id-like columns ──────────────────


def test_raw_appointment_rows_produce_no_id_based_trend_metrics():
    engine = AnalyticsEngine()
    rows = [
        {
            "randevu_id": 142,
            "hasta_id": 984,
            "doktor_id": 13,
            "bolum_id": 1,
            "randevu_tarihi": "2026-01-14",
            "durum": "iptal",
        },
        {
            "randevu_id": 143,
            "hasta_id": 557,
            "doktor_id": 1,
            "bolum_id": 11,
            "randevu_tarihi": "2026-01-15",
            "durum": "tamamlandi",
        },
    ]
    data = _query_result(
        ["randevu_id", "hasta_id", "doktor_id", "bolum_id", "randevu_tarihi", "durum"],
        rows,
    )

    result = engine.analyze(TREND_QUESTION, data)

    assert result.metric_column is None
    assert result.metrics == {"count": 0}
    assert "growth_rate" not in result.metrics
    assert "highest_period" not in result.metrics


def test_multi_metric_aggregation_prefers_question_subject_column():
    engine = AnalyticsEngine()
    data = _query_result(
        ["ay", "toplam_randevu", "beklemede", "iptal_edildi"],
        [
            {"ay": "2026-01", "toplam_randevu": 452, "beklemede": 0, "iptal_edildi": 0},
            {"ay": "2026-02", "toplam_randevu": 719, "beklemede": 0, "iptal_edildi": 0},
            {"ay": "2026-03", "toplam_randevu": 720, "beklemede": 0, "iptal_edildi": 0},
        ],
    )

    result = engine.analyze(TREND_QUESTION, data)

    assert result.metric_column == "toplam_randevu"
    assert result.metrics["total"] == 1891.0


def test_monthly_aggregation_still_produces_trend_metrics():
    engine = AnalyticsEngine()
    data = _query_result(
        ["ay", "adet"],
        [
            {"ay": "2026-01", "adet": 201},
            {"ay": "2026-02", "adet": 240},
            {"ay": "2026-03", "adet": 260},
        ],
    )

    result = engine.analyze(TREND_QUESTION, data)

    assert result.metric_column == "adet"
    assert result.data_shape.value == "time_series"
    assert "trend_direction" in result.metrics
