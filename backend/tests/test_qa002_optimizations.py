"""Regression tests for QA-002 — LLM pipeline optimization.

Covers:
1. Analytical reports reuse the Insight Engine narrative instead of a second
   LLM call (insight-reuse path).
2. Behavior preservation: without a usable insight narrative, the LLM report
   path is unchanged.
3. Prompt reductions: raw SQL removed from the report prompt; duplicated
   analytics/insight fields removed from the insight prompt payload.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.analytics.models import AnalyticsResult, DataShape
from app.application_models.workflow_models import QueryResult
from app.insights.models import InsightConfidence, InsightResult
from app.insights.prompt_builder import InsightPromptBuilder
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse
from app.services.report_service import ReportService


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


TREND_RESULT = _query_result(
    ["ay", "randevu_sayisi"],
    [
        {"ay": "2026-01", "randevu_sayisi": 452},
        {"ay": "2026-02", "randevu_sayisi": 719},
        {"ay": "2026-03", "randevu_sayisi": 720},
    ],
)


def _insights(confidence=InsightConfidence.HIGH) -> InsightResult:
    return InsightResult(
        title="Randevu Trendi",
        summary="Randevular yılın ilk çeyreğinde artış gösterdi.",
        highlights=["Şubat ayında %59 artış görüldü."],
        observations=["Mart ayı Şubat ile aynı seviyede kaldı."],
        considerations=[],
        rules=[],
        confidence=confidence,
        llm_generated=True,
        provider="OllamaProvider",
        model="qwen3:8b",
        duration_ms=100.0,
    )


def _report_service() -> tuple[ReportService, AsyncMock]:
    prompt_service = AsyncMock()
    prompt_service.render_report_prompt.return_value = "prompt"
    llm_provider = AsyncMock(spec=ILLMProvider)
    llm_provider.generate.return_value = LLMResponse(
        content="# LLM Raporu\n\nMetin.", model="mock", latency_ms=5.0
    )
    llm_provider.get_metadata.return_value = {"provider": "ollama"}
    return ReportService(prompt_service=prompt_service, llm_provider=llm_provider), llm_provider


# ── 1. Insight reuse eliminates the report LLM call ───────────────────────────


@pytest.mark.asyncio
async def test_analytical_report_reuses_insight_narrative_without_llm():
    service, llm_provider = _report_service()

    report = await service.generate_report(
        question="Son 6 ayın randevularını analiz et",
        sql="SELECT ...",
        query_result=TREND_RESULT,
        insights=_insights(),
    )

    llm_provider.generate.assert_not_called()
    assert report.provider == "insight_reuse"
    assert report.title == "Randevu Trendi"
    assert "Randevular yılın ilk çeyreğinde artış gösterdi." in report.markdown
    assert "Şubat ayında %59 artış görüldü." in report.markdown
    # The data table is preserved in the report body.
    assert "| 2026-01 | 452 |" in report.markdown


@pytest.mark.asyncio
async def test_analytical_report_without_insights_still_uses_llm():
    service, llm_provider = _report_service()

    report = await service.generate_report(
        question="Son 6 ayın randevularını analiz et",
        sql="SELECT ...",
        query_result=TREND_RESULT,
        insights=None,
    )

    llm_provider.generate.assert_called_once()
    assert report.provider == "ollama"


@pytest.mark.asyncio
async def test_low_confidence_insights_do_not_replace_llm_report():
    service, llm_provider = _report_service()

    report = await service.generate_report(
        question="Son 6 ayın randevularını analiz et",
        sql="SELECT ...",
        query_result=TREND_RESULT,
        insights=_insights(confidence=InsightConfidence.LOW),
    )

    llm_provider.generate.assert_called_once()
    assert report.provider == "ollama"


@pytest.mark.asyncio
async def test_non_analytical_report_ignores_insights_and_uses_template():
    service, llm_provider = _report_service()
    count_result = _query_result(["toplam"], [{"toplam": 42}])

    report = await service.generate_report(
        question="Kaç randevu var?",
        sql="SELECT COUNT(*) AS toplam FROM randevular",
        query_result=count_result,
        insights=_insights(),
    )

    llm_provider.generate.assert_not_called()
    assert report.provider == "template"


# ── 2. Prompt reductions ──────────────────────────────────────────────────────


def test_report_prompt_template_contains_no_raw_sql():
    template = Path("app/prompts/report_generation.md").read_text(encoding="utf-8")
    assert "{query}" not in template
    assert "SQL:" not in template


@pytest.mark.asyncio
async def test_single_value_insight_skips_llm():
    from app.insights.insight_engine import InsightEngine

    llm_provider = AsyncMock(spec=ILLMProvider)
    analytics = AnalyticsResult(
        analytics_type="summary",
        intents=[],
        data_shape=DataShape.SINGLE_VALUE,
        metrics={"count": 1, "total": 42.0},
        insights={"value": 42.0},
        visualization=None,
        metric_column="doktor_sayisi",
        label_column=None,
        row_count=1,
        duration_ms=1.0,
    )

    result = await InsightEngine(llm_provider=llm_provider).generate(analytics)

    llm_provider.generate.assert_not_called()
    assert result.llm_generated is False
    assert result.title
    assert result.summary


def test_insight_payload_omits_duplicated_metric_values():
    builder = InsightPromptBuilder()
    analytics = AnalyticsResult(
        analytics_type="trend",
        intents=[],
        data_shape=DataShape.TIME_SERIES,
        metrics={
            "count": 3,
            "total": 1891.0,
            "average": 630.33,
            "growth_rate": 59.3,
            "trend_direction": "upward",
        },
        insights={
            "trend": "upward",
            "growth_rate": 59.3,
            "total": 1891.0,
            "average": 630.33,
        },
        visualization=None,
        metric_column="randevu_sayisi",
        label_column="ay",
        row_count=3,
        duration_ms=1.0,
    )

    payload = builder.analytics_payload(analytics)

    # Every insight entry duplicates a metric value, so the block is omitted.
    assert "insights" not in payload
    assert payload["metrics"]["growth_rate"] == 59.3
