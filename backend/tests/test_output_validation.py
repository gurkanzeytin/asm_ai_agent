"""Tests for app.insights.output_validation.validate_and_repair — the
lightweight, no-second-LLM-call safety net over LLM-produced insight
narratives (English title/body detection, missing-limitation injection,
causal-certainty stripping)."""

from app.analytics.models import AnalyticsResult, DataShape
from app.analytics.trend_analysis import TrendMetrics
from app.insights.models import InsightNarrative, InsightRule
from app.insights.output_validation import validate_and_repair


def _analytics(**overrides) -> AnalyticsResult:
    base = dict(
        analytics_type="trend",
        data_shape=DataShape.TIME_SERIES,
        metrics={"count": 3, "total": 30.0},
        row_count=3,
    )
    base.update(overrides)
    return AnalyticsResult(**base)


def test_empty_title_falls_back_to_deterministic_narrative():
    narrative = InsightNarrative(title="", summary="", highlights=[], observations=[])

    repaired, verdict = validate_and_repair(narrative, _analytics(), [])

    assert repaired.title
    assert verdict.narrative_replaced is True
    assert verdict.reason == "empty_title_or_summary"


def test_english_title_is_replaced_not_whole_narrative():
    narrative = InsightNarrative(
        title="Appointment Trend Overview",
        summary="Değerler dönem boyunca artış gösterdi.",
        highlights=["Toplam 30 kayıt bulundu."],
        observations=[],
    )

    repaired, verdict = validate_and_repair(narrative, _analytics(), [])

    assert repaired.title != "Appointment Trend Overview"
    assert repaired.title == "Trend Analizi"
    assert repaired.summary == narrative.summary  # body untouched
    assert verdict.title_replaced is True
    assert verdict.narrative_replaced is False


def test_english_body_triggers_full_deterministic_fallback():
    narrative = InsightNarrative(
        title="Trend Analizi",
        summary="The values increased significantly and the trend is stable.",
        highlights=["Growth detected in the period"],
        observations=[],
    )

    repaired, verdict = validate_and_repair(narrative, _analytics(), [])

    assert verdict.narrative_replaced is True
    assert verdict.language_ok is False
    assert repaired.summary != narrative.summary


def test_missing_comparison_limitation_is_appended():
    narrative = InsightNarrative(
        title="Dönem Karşılaştırması",
        summary="'Merkez' için sonuçlar özetlendi.",
        highlights=[],
        observations=[],
        considerations=[],
    )
    analytics = _analytics(
        analytics_type="comparison",
        data_shape=DataShape.CATEGORICAL,
        comparison_sufficient=False,
        comparison_category_count=1,
        comparison_limitation_reason=(
            "Seçilen kapsamda yalnızca bir kategori bulunduğu için kategoriler "
            "arası karşılaştırma yapılamadı."
        ),
    )

    repaired, verdict = validate_and_repair(narrative, analytics, [])

    assert any(
        analytics.comparison_limitation_reason in text for text in repaired.considerations
    )
    assert "comparison_limitation" in verdict.missing_limitations_added


def test_missing_partial_period_limitation_is_appended():
    narrative = InsightNarrative(
        title="Trend Analizi", summary="Değerler yükseldi.", highlights=[], considerations=[]
    )
    trend_metrics = TrendMetrics(
        endpoint_change=5.0,
        endpoint_percentage_change=10.0,
        endpoint_direction="upward",
        slope=1.0,
        slope_direction="upward",
        trend_consistency="consistent_upward",
        comparable_period_count=3,
        comparison_excluded_partial_period=True,
        excluded_periods=["2026-07"],
    )
    analytics = _analytics(trend_metrics=trend_metrics)

    repaired, verdict = validate_and_repair(narrative, analytics, [])

    assert any("2026-07" in text and "tamamlanmadığı" in text for text in repaired.considerations)
    assert "partial_period_excluded" in verdict.missing_limitations_added


def test_causal_certainty_sentence_is_dropped_not_rewritten():
    narrative = InsightNarrative(
        title="Trend Analizi",
        summary="Değerler yükseldi.",
        highlights=[],
        considerations=["Bu artışın kesin nedeni personel değişikliğidir."],
    )

    repaired, verdict = validate_and_repair(narrative, _analytics(), [])

    assert repaired.considerations == []
    assert verdict.causal_certainty_dropped == 1


def test_valid_turkish_narrative_passes_through_unchanged():
    narrative = InsightNarrative(
        title="Trend Analizi",
        summary="Değerler dönem boyunca yükseldi.",
        highlights=["Toplam 30 kayıt bulundu."],
        observations=["Ortalama değer 10."],
        considerations=[],
    )

    repaired, verdict = validate_and_repair(narrative, _analytics(), [])

    assert repaired == narrative
    assert verdict.language_ok is True
    assert verdict.title_replaced is False
    assert verdict.narrative_replaced is False


def test_insufficient_evidence_rule_untouched_when_no_english():
    narrative = InsightNarrative(
        title="Trend Analizi", summary="Yeterli veri yok.", highlights=[]
    )

    repaired, verdict = validate_and_repair(
        narrative, _analytics(), [InsightRule.INSUFFICIENT_EVIDENCE]
    )

    assert repaired.title == "Trend Analizi"
    assert verdict.narrative_replaced is False
