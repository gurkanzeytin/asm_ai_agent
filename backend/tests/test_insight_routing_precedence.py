"""Regression tests for the deterministic-routing precedence fix.

Root cause fixed here: InsightRouter.compute_complexity() previously gave
OUTLIER_DETECTED a flat +2 and "rich baseline metrics" (count/total/average/
median/min/max, which are computed for almost any non-empty result) a flat
+1, regardless of shape or row count. A perfectly ordinary 3-row categorical
distribution (e.g. "Beklemede: 8, Giriş Yapılmış: 3, Gelmedi: 2") routinely
fires both DOMINANT_CATEGORY and OUTLIER_DETECTED, so its complexity score hit
the remote threshold (3) even though the result is trivially simple — sending
a 38-second NVIDIA DeepSeek round trip for a question that needed no LLM call
at all.

The fix: deterministic candidacy is now decided BEFORE complexity scoring,
purely from analysis-family shape signals (data_shape, intents, row_count) —
never from which generic rules fired. OUTLIER_DETECTED only contributes to the
complexity score when combined with a genuine complexity driver (a time
series, many rows/categories, or multiple intents).
"""

import pytest

from app.analytics.models import AnalyticsIntent, AnalyticsResult, DataShape
from app.insights.insight_engine import InsightEngine
from app.insights.models import InsightConfidence, InsightRule
from app.insights.routing import InsightGenerationMode, InsightRouter
from app.llm.schemas import LLMResponse


class _NeverCallProvider:
    """Raises if invoked at all — proves the deterministic path made zero LLM calls."""

    def __init__(self):
        self.calls = 0

    async def generate(self, prompt, think=True, options=None):
        self.calls += 1
        raise AssertionError("This provider must never be called for a simple distribution.")


class _FakeProvider:
    def __init__(self, model="fake-model", latency_ms=2000.0):
        self.calls = 0
        self.model = model
        self.latency_ms = latency_ms

    async def generate(self, prompt, think=True, options=None):
        self.calls += 1
        import json

        payload = {"title": "T", "summary": "S", "highlights": [], "observations": []}
        return LLMResponse(
            content=json.dumps(payload),
            model=self.model,
            latency_ms=self.latency_ms,
            prompt_tokens=100,
            completion_tokens=30,
            finish_reason="stop",
        )


def _live_bug_distribution() -> AnalyticsResult:
    """Reproduces the exact reported live case: 3-row categorical distribution,
    DOMINANT_CATEGORY + OUTLIER_DETECTED both fire, must stay deterministic."""
    return AnalyticsResult(
        analytics_type="distribution",
        intents=[],
        data_shape=DataShape.CATEGORICAL,
        metrics={
            "count": 13,
            "total": 13.0,
            "average": 4.33,
            "maximum": 8.0,
            "median": 3.0,
            "minimum": 2.0,
            "highest_value": 8.0,
            "lowest_value": 2.0,
            "top_category": "Beklemede",
            "bottom_category": "Gelmedi",
            "distribution": {"Beklemede": 61.54, "Giriş Yapılmış": 23.08, "Gelmedi": 15.38},
            "ranking": [
                {"label": "Beklemede", "value": 8},
                {"label": "Giriş Yapılmış", "value": 3},
                {"label": "Gelmedi", "value": 2},
            ],
        },
        row_count=3,
    )


def _one_dim_top_n() -> AnalyticsResult:
    return AnalyticsResult(
        analytics_type="ranking",
        intents=[AnalyticsIntent.RANKING],
        data_shape=DataShape.CATEGORICAL,
        metrics={
            "count": 4,
            "total": 100.0,
            "average": 25.0,
            "maximum": 50.0,
            "top_category": "X",
            "top_n": [
                {"label": "X", "value": 50.0},
                {"label": "Y", "value": 30.0},
                {"label": "Z", "value": 20.0},
            ],
            "distribution": {"X": 50.0, "Y": 30.0, "Z": 20.0},
        },
        row_count=4,
    )


def _explicit_time_series_anomaly() -> AnalyticsResult:
    """Genuine anomaly: time-series shape, several periods, outlier rule fires."""
    return AnalyticsResult(
        analytics_type="trend",
        intents=[],
        data_shape=DataShape.TIME_SERIES,
        metrics={
            "count": 10,
            "total": 5000.0,
            "average": 500.0,
            "maximum": 3000.0,
            "minimum": 50.0,
            "median": 480.0,
            "highest_value": 3000.0,
            "lowest_value": 50.0,
            "growth_rate": 240.0,
            "trend_direction": "upward",
            "highest_period": "2026-06",
            "lowest_period": "2026-01",
            "largest_change": "2026-06",
        },
        row_count=10,
    )


def _multi_metric_anomaly() -> AnalyticsResult:
    """Genuine cross-dimensional anomaly: TABULAR + multiple intents + outlier context."""
    return AnalyticsResult(
        analytics_type="general",
        intents=[AnalyticsIntent.TREND, AnalyticsIntent.COMPARISON, AnalyticsIntent.RANKING],
        data_shape=DataShape.TABULAR,
        metrics={
            "count": 15,
            "total": 3000.0,
            "average": 200.0,
            "maximum": 1800.0,
            "minimum": 5.0,
            "median": 150.0,
        },
        row_count=15,
    )


def _medium_trend() -> AnalyticsResult:
    return AnalyticsResult(
        analytics_type="trend",
        intents=[],
        data_shape=DataShape.TIME_SERIES,
        metrics={
            "count": 6,
            "total": 1587.0,
            "average": 264.5,
            "growth_rate": 18.4,
            "trend_direction": "upward",
        },
        row_count=6,
    )


def _make_rules_engine_rules(analytics: AnalyticsResult) -> list[InsightRule]:
    from app.insights.rules_engine import InsightRulesEngine

    return InsightRulesEngine().evaluate(analytics)


# ── 1-4: deterministic precedence over generic rules ──────────────────────────


def test_simple_distribution_routes_deterministic():
    router = InsightRouter(remote_available=True)
    analytics = _live_bug_distribution()
    rules = _make_rules_engine_rules(analytics)
    assert InsightRule.DOMINANT_CATEGORY in rules
    assert InsightRule.OUTLIER_DETECTED in rules

    decision = router.decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.deterministic_candidate is True
    assert decision.deterministic_reason == "simple_distribution"
    assert decision.mode == InsightGenerationMode.DETERMINISTIC
    assert decision.selected_provider == "deterministic"
    assert decision.selected_model == "templates"


def test_dominant_category_alone_does_not_trigger_remote():
    analytics = AnalyticsResult(
        analytics_type="distribution",
        data_shape=DataShape.CATEGORICAL,
        metrics={
            "count": 3,
            "total": 100.0,
            "average": 33.3,
            "maximum": 60.0,
            "top_category": "A",
            "distribution": {"A": 60.0, "B": 25.0, "C": 15.0},
        },
        row_count=3,
    )
    rules = [InsightRule.DOMINANT_CATEGORY]

    decision = InsightRouter(remote_available=True).decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode != InsightGenerationMode.REMOTE_LLM
    assert decision.mode == InsightGenerationMode.DETERMINISTIC


def test_outlier_detected_alone_does_not_trigger_remote():
    analytics = _live_bug_distribution()
    rules = [InsightRule.OUTLIER_DETECTED]

    decision = InsightRouter(remote_available=True).decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode != InsightGenerationMode.REMOTE_LLM
    assert decision.mode == InsightGenerationMode.DETERMINISTIC


def test_generic_rule_combination_on_small_categorical_remains_deterministic():
    """The exact reported live bug: DOMINANT_CATEGORY + OUTLIER_DETECTED on a
    3-row distribution must not route remote."""
    analytics = _live_bug_distribution()
    rules = [InsightRule.DOMINANT_CATEGORY, InsightRule.OUTLIER_DETECTED]

    decision = InsightRouter(remote_available=True).decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.DETERMINISTIC
    assert decision.selected_provider == "deterministic"


# ── 5-6: genuine anomaly routing preserved ─────────────────────────────────────


def test_explicit_time_series_anomaly_routes_remote_when_policy_allows():
    analytics = _explicit_time_series_anomaly()
    rules = [InsightRule.OUTLIER_DETECTED, InsightRule.HIGH_GROWTH, InsightRule.POSITIVE_TREND]

    decision = InsightRouter(remote_available=True).decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.REMOTE_LLM
    assert decision.selected_provider == "nvidia"
    assert decision.complexity_score >= 3


def test_multi_metric_anomaly_routes_remote():
    analytics = _multi_metric_anomaly()
    rules = [InsightRule.OUTLIER_DETECTED]

    decision = InsightRouter(remote_available=True).decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.REMOTE_LLM
    assert decision.selected_provider == "nvidia"
    assert "cross_dimensional_multi_intent_analysis" in decision.complexity_factors


# ── 7: one-dimensional top-N remains deterministic ────────────────────────────


def test_one_dimensional_top_n_remains_deterministic():
    analytics = _one_dim_top_n()
    rules = _make_rules_engine_rules(analytics)

    decision = InsightRouter(remote_available=True).decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.DETERMINISTIC
    assert decision.deterministic_reason == "simple_distribution"


# ── 8: deterministic metadata consistency ─────────────────────────────────────


@pytest.mark.asyncio
async def test_deterministic_metadata_is_consistent():
    provider = _NeverCallProvider()
    engine = InsightEngine(local_llm_provider=provider, remote_llm_provider=provider)
    analytics = _live_bug_distribution()

    result = await engine.generate(analytics)

    assert provider.calls == 0
    assert result.routing_mode == "deterministic"
    assert result.provider == "deterministic"
    assert result.model == "templates"
    assert result.llm_generated is False
    assert result.llm_latency_ms == 0.0
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.attempts == 0


# ── 9: deterministic distribution output content ──────────────────────────────


@pytest.mark.asyncio
async def test_deterministic_distribution_output_includes_total_leader_count_percentage():
    engine = InsightEngine(local_llm_provider=_NeverCallProvider())
    analytics = _live_bug_distribution()

    result = await engine.generate(analytics)

    combined = result.summary + " " + " ".join(result.highlights + result.observations)
    assert "13" in combined  # total
    assert "Beklemede" in combined  # leading category
    assert "8" in combined  # leading category count
    assert "61,5" in combined  # leading category percentage (Turkish decimal comma)


# ── 10: no "significant" wording without a supporting threshold ──────────────


def test_no_significant_wording_in_deterministic_narrative():
    from app.insights import templates

    analytics = _live_bug_distribution()
    rules = [InsightRule.DOMINANT_CATEGORY, InsightRule.OUTLIER_DETECTED]

    narrative = templates.build_deterministic_narrative(analytics, rules)

    combined = narrative.summary + " " + " ".join(narrative.highlights + narrative.observations)
    full_text = combined.lower()
    assert "significant" not in full_text
    assert "önemli" not in full_text
    assert "anomali" not in full_text


def test_no_significant_wording_in_observation_templates():
    from app.intelligence import templates as obs_templates

    for wording in obs_templates.RULE_WORDINGS.values():
        assert "significant" not in wording.lower()
    assert "significant" not in obs_templates.SIGNIFICANT_SPREAD_WORDING.lower()


# ── 11-12: existing Qwen/DeepSeek routing for genuinely complex cases ────────


def test_medium_complexity_still_routes_to_qwen():
    analytics = _medium_trend()
    rules = [InsightRule.HIGH_GROWTH, InsightRule.POSITIVE_TREND]

    decision = InsightRouter(remote_available=True).decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.LOCAL_LLM
    assert decision.selected_provider == "ollama"


def test_genuinely_complex_case_still_routes_to_deepseek():
    analytics = _explicit_time_series_anomaly()
    rules = [InsightRule.OUTLIER_DETECTED, InsightRule.HIGH_GROWTH]

    decision = InsightRouter(remote_available=True).decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.REMOTE_LLM
    assert decision.selected_provider == "nvidia"


# ── 13: no real network calls ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_real_network_call_for_deterministic_case():
    """_NeverCallProvider raises AssertionError if invoked — proves zero calls."""
    engine = InsightEngine(
        local_llm_provider=_NeverCallProvider(), remote_llm_provider=_NeverCallProvider()
    )
    result = await engine.generate(_live_bug_distribution())
    assert result.provider == "deterministic"


@pytest.mark.asyncio
async def test_medium_and_complex_cases_use_fakes_not_real_network():
    local = _FakeProvider(model="qwen3:8b")
    remote = _FakeProvider(model="deepseek-ai/deepseek-v4-pro")
    engine = InsightEngine(local_llm_provider=local, remote_llm_provider=remote)

    medium_result = await engine.generate(_medium_trend())
    assert medium_result.provider == "ollama"
    assert local.calls == 1
    assert remote.calls == 0

    complex_result = await engine.generate(_explicit_time_series_anomaly())
    assert complex_result.provider == "nvidia"
    assert remote.calls == 1
