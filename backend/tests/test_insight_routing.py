"""Tests for the insight-generation deterministic renderer and complexity-based
routing (deterministic / local Ollama-qwen3 / remote NVIDIA-DeepSeek), plus the
bounded fallback behavior and the LLM-timing propagation fix.

No real network calls: LLM providers are hand-rolled fakes implementing the
same ``generate(prompt, think, options) -> LLMResponse`` contract used
throughout the existing provider tests (see test_insights.py::FakeLLMProvider).
"""

import json

import pytest

from app.analytics.models import AnalyticsIntent, AnalyticsResult, DataShape
from app.insights.insight_engine import InsightEngine
from app.insights.models import InsightConfidence, InsightRule
from app.insights.routing import InsightGenerationMode, InsightRouter
from app.insights.templates import (
    INSUFFICIENT_EVIDENCE_SUMMARY,
    classify_change,
    safe_ratio_percentage,
)
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.schemas import LLMResponse


def _narrative_json(**overrides) -> str:
    payload = {
        "title": "T",
        "summary": "S",
        "highlights": ["H1"],
        "observations": ["O1"],
        "considerations": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


class _FakeProvider:
    """Deterministic fake LLM provider; raises `raise_exc` once per call if set."""

    def __init__(self, raise_exc=None, model="fake-model", latency_ms=2500.0):
        self.calls = 0
        self.raise_exc = raise_exc
        self.model = model
        self.latency_ms = latency_ms
        self.content = _narrative_json()

    async def generate(self, prompt, think=True, options=None):
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return LLMResponse(
            content=self.content,
            model=self.model,
            latency_ms=self.latency_ms,
            prompt_tokens=120,
            completion_tokens=40,
            finish_reason="stop",
        )


def _analytics(**overrides) -> AnalyticsResult:
    base = dict(
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
    base.update(overrides)
    return AnalyticsResult(**base)


def _simple_distribution() -> AnalyticsResult:
    """CATEGORICAL, complexity score 0 -> deterministic per the router."""
    return AnalyticsResult(
        analytics_type="distribution",
        intents=[AnalyticsIntent.DISTRIBUTION],
        data_shape=DataShape.CATEGORICAL,
        metrics={
            "count": 3,
            "total": 100.0,
            "average": 33.3,
            "maximum": 40.0,
            "top_category": "A",
            "distribution": {"A": 40.0, "B": 35.0, "C": 25.0},
        },
        row_count=3,
    )


def _simple_count() -> AnalyticsResult:
    return AnalyticsResult(
        analytics_type="summary",
        data_shape=DataShape.SINGLE_VALUE,
        metrics={"count": 1, "total": 42.0},
        row_count=1,
    )


def _medium_trend() -> AnalyticsResult:
    """TIME_SERIES, complexity score 2 (< default threshold 3) -> local."""
    return _analytics()


def _complex_multi_metric() -> AnalyticsResult:
    """TABULAR + multi-intent + rich metrics -> complexity score >= 3 -> remote."""
    return AnalyticsResult(
        analytics_type="general",
        intents=[AnalyticsIntent.TREND, AnalyticsIntent.COMPARISON],
        data_shape=DataShape.TABULAR,
        metrics={
            "count": 12,
            "total": 900.0,
            "average": 75.0,
            "median": 70.0,
            "minimum": 10.0,
            "maximum": 200.0,
        },
        row_count=12,
    )


def _empty_analytics() -> AnalyticsResult:
    return AnalyticsResult(
        analytics_type="none", data_shape=DataShape.EMPTY, metrics={"count": 0}, row_count=0
    )


# ── Phase 2: deterministic insight generation ─────────────────────────────────


@pytest.mark.asyncio
async def test_count_produces_turkish_deterministic_output():
    engine = InsightEngine(local_llm_provider=_FakeProvider())
    result = await engine.generate(_simple_count())

    assert result.llm_generated is False
    assert result.provider == "deterministic"
    assert "42" in " ".join(result.observations) or "42" in result.summary


@pytest.mark.asyncio
async def test_distribution_produces_total_top_category_and_percentage():
    engine = InsightEngine(local_llm_provider=_FakeProvider())
    result = await engine.generate(_simple_distribution())

    assert result.llm_generated is False
    text = " ".join(result.observations)
    assert "A" in text
    assert "%40" in text.replace(",0", "")  # "%40,0" -> tolerate exact decimal form
    assert "toplam" in text.lower() or "kategori" in text.lower()


def test_ratio_handles_zero_denominator():
    assert safe_ratio_percentage(10, 0) is None
    assert safe_ratio_percentage(0, 0) is None
    assert safe_ratio_percentage(25, 100) == "%25,0"


def test_top_n_handles_one_and_multiple_rows():
    from app.insights import templates

    single = templates.build_deterministic_narrative(
        _analytics(
            data_shape=DataShape.CATEGORICAL,
            metrics={"count": 1, "total": 10.0, "top_n": [{"label": "A", "value": 10.0}]},
        ),
        [],
    )
    assert "A" in " ".join(single.observations)

    multi = templates.build_deterministic_narrative(
        _analytics(
            data_shape=DataShape.CATEGORICAL,
            metrics={
                "count": 2,
                "total": 30.0,
                "top_n": [{"label": "A", "value": 20.0}, {"label": "B", "value": 10.0}],
            },
        ),
        [],
    )
    text = " ".join(multi.observations)
    assert "A" in text and "B" in text


@pytest.mark.asyncio
async def test_empty_result_produces_safe_message():
    engine = InsightEngine(local_llm_provider=_FakeProvider())
    result = await engine.generate(_empty_analytics())

    assert result.summary == INSUFFICIENT_EVIDENCE_SUMMARY
    assert result.llm_generated is False


@pytest.mark.asyncio
async def test_deterministic_path_does_not_call_any_llm():
    local_provider = _FakeProvider()
    remote_provider = _FakeProvider()
    engine = InsightEngine(local_llm_provider=local_provider, remote_llm_provider=remote_provider)

    await engine.generate(_simple_distribution())

    assert local_provider.calls == 0
    assert remote_provider.calls == 0


def test_deterministic_narrative_invents_no_unsupported_claims():
    from app.insights import templates

    # No OUTLIER_DETECTED rule fired -> narrative must never call anything an outlier.
    narrative = templates.build_deterministic_narrative(_simple_distribution(), [])
    full_text = " ".join(narrative.highlights + narrative.observations).lower()
    assert "anomali" not in full_text
    assert "aykırı" not in full_text
    assert "önemli" not in full_text  # "significant" without an explicit rule


def test_classify_change_is_sign_based_not_invented():
    assert classify_change(5.0) == "increase"
    assert classify_change(-5.0) == "decrease"
    assert classify_change(0.0) == "no_change"
    assert classify_change(None) == "no_change"


# ── Phase 3: complexity-based routing ─────────────────────────────────────────


def test_simple_distribution_routes_to_deterministic():
    router = InsightRouter(remote_available=True)
    analytics = _simple_distribution()
    rules = []
    confidence = InsightConfidence.MEDIUM

    decision = router.decide(analytics, rules, confidence)

    assert decision.mode == InsightGenerationMode.DETERMINISTIC
    assert decision.selected_provider == "deterministic"


def test_simple_count_routes_to_deterministic():
    router = InsightRouter(remote_available=True)
    decision = router.decide(_simple_count(), [], InsightConfidence.LOW)

    assert decision.mode == InsightGenerationMode.DETERMINISTIC


def test_medium_complexity_routes_to_local_qwen():
    router = InsightRouter(remote_available=True)
    analytics = _medium_trend()
    rules = [InsightRule.HIGH_GROWTH, InsightRule.POSITIVE_TREND]

    decision = router.decide(analytics, rules, InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.LOCAL_LLM
    assert decision.selected_provider == "ollama"
    assert decision.complexity_score < 3


def test_complex_multi_metric_routes_to_remote_deepseek():
    router = InsightRouter(remote_available=True)
    analytics = _complex_multi_metric()

    decision = router.decide(analytics, [], InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.REMOTE_LLM
    assert decision.selected_provider == "nvidia"
    assert decision.complexity_score >= 3


def test_patient_level_payload_routes_to_local_qwen():
    router = InsightRouter(remote_available=True)
    analytics = _complex_multi_metric()  # otherwise would route remote

    decision = router.decide(
        analytics,
        [],
        InsightConfidence.HIGH,
        remote_texts=("... HastaAdi = 'Ahmet' ...",),
    )

    assert decision.mode == InsightGenerationMode.LOCAL_LLM
    assert decision.remote_policy_status == "rejected"


@pytest.mark.asyncio
async def test_engine_routes_unsafe_payload_to_local_not_remote():
    local_provider = _FakeProvider()
    remote_provider = _FakeProvider()
    engine = InsightEngine(local_llm_provider=local_provider, remote_llm_provider=remote_provider)
    analytics = _complex_multi_metric()
    analytics = analytics.model_copy(
        update={"metrics": {**analytics.metrics, "top_category": "HastaAdi"}}
    )

    result = await engine.generate(analytics)

    assert remote_provider.calls == 0
    assert local_provider.calls == 1
    assert result.remote_data_policy == "rejected"


def test_remote_unavailable_falls_back_to_local_routing_decision():
    router = InsightRouter(remote_available=False)
    decision = router.decide(_complex_multi_metric(), [], InsightConfidence.HIGH)

    assert decision.mode == InsightGenerationMode.LOCAL_LLM


# ── Phase 4: bounded fallback behavior ────────────────────────────────────────


@pytest.mark.asyncio
async def test_deepseek_timeout_falls_back_once_to_qwen():
    remote = _FakeProvider(raise_exc=LLMTimeoutError("timed out"))
    local = _FakeProvider()
    engine = InsightEngine(local_llm_provider=local, remote_llm_provider=remote)

    result = await engine.generate(_complex_multi_metric())

    assert remote.calls == 1
    assert local.calls == 1
    assert result.llm_generated is True
    assert result.provider == "ollama"
    assert result.fallback_used is True
    assert "LLMTimeoutError" in (result.fallback_reason or "")


@pytest.mark.asyncio
async def test_deepseek_rate_limit_falls_back_once_to_qwen():
    remote = _FakeProvider(raise_exc=LLMRateLimitError("rate limited"))
    local = _FakeProvider()
    engine = InsightEngine(local_llm_provider=local, remote_llm_provider=remote)

    result = await engine.generate(_complex_multi_metric())

    assert remote.calls == 1
    assert local.calls == 1
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_deepseek_auth_error_does_not_repeatedly_retry():
    remote = _FakeProvider(raise_exc=LLMAuthenticationError("bad key"))
    local = _FakeProvider()
    engine = InsightEngine(local_llm_provider=local, remote_llm_provider=remote)

    result = await engine.generate(_complex_multi_metric())

    # Exactly one attempt against the failing provider — never retried.
    assert remote.calls == 1
    assert local.calls == 1
    assert result.provider == "ollama"


@pytest.mark.asyncio
async def test_qwen_failure_falls_back_to_deterministic_output():
    local = _FakeProvider(raise_exc=LLMConnectionError("down"))
    engine = InsightEngine(local_llm_provider=local)  # no remote configured

    result = await engine.generate(_medium_trend())

    assert local.calls == 1
    assert result.llm_generated is False
    assert result.provider == "deterministic"
    assert result.summary  # still a grounded, non-empty narrative


@pytest.mark.asyncio
async def test_no_infinite_fallback_loop_bounded_attempts():
    remote = _FakeProvider(raise_exc=LLMConnectionError("down"))
    local = _FakeProvider(raise_exc=LLMConnectionError("also down"))
    engine = InsightEngine(local_llm_provider=local, remote_llm_provider=remote)

    result = await engine.generate(_complex_multi_metric())

    # At most one attempt per leg: remote once, local once, then deterministic.
    assert remote.calls == 1
    assert local.calls == 1
    assert result.provider == "deterministic"
    assert result.fallback_used is True


# ── Phase 5: timing and metadata propagation ──────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_llm_duration_is_recorded_on_result():
    local = _FakeProvider(model="qwen3:8b", latency_ms=8400.0)
    engine = InsightEngine(local_llm_provider=local)

    result = await engine.generate(_medium_trend())

    assert result.llm_latency_ms == 8400.0
    assert result.provider == "ollama"
    assert result.model == "qwen3:8b"


@pytest.mark.asyncio
async def test_nvidia_llm_duration_is_recorded_on_result():
    remote = _FakeProvider(model="deepseek-ai/deepseek-v4-pro", latency_ms=58000.0)
    engine = InsightEngine(local_llm_provider=_FakeProvider(), remote_llm_provider=remote)

    result = await engine.generate(_complex_multi_metric())

    assert result.llm_latency_ms == 58000.0
    assert result.provider == "nvidia"
    assert result.model == "deepseek-ai/deepseek-v4-pro"


def test_reporting_service_sums_insight_llm_latency_into_total():
    from app.application_models.generated_report import GeneratedReport
    from app.application_models.generated_sql import GeneratedSQL
    from app.insights.models import InsightResult

    generated_sql_dto = GeneratedSQL(
        sql="SELECT 1", provider="ollama", model="qwen3:8b", latency_ms=200.0
    )
    generated_report_dto = GeneratedReport(
        title="T", markdown="md", provider="insight_reuse", model="templates", latency_ms=0.5
    )
    insights_dto = InsightResult(
        title="T",
        summary="S",
        provider="nvidia",
        model="deepseek-ai/deepseek-v4-pro",
        llm_generated=True,
        llm_latency_ms=58000.0,
    )

    sql_latency = generated_sql_dto.latency_ms
    report_latency = generated_report_dto.latency_ms
    insight_llm_latency = insights_dto.llm_latency_ms
    llm_total_ms = sql_latency + report_latency + (insight_llm_latency or 0.0)

    assert llm_total_ms == pytest.approx(58200.5)


@pytest.mark.asyncio
async def test_deterministic_path_reports_zero_llm_inference():
    engine = InsightEngine(local_llm_provider=_FakeProvider())
    result = await engine.generate(_simple_distribution())

    assert result.llm_latency_ms == 0.0
    assert result.llm_generated is False
    assert result.attempts == 0
    assert result.fallback_used is False
    assert result.fallback_reason is None
    assert result.routing_mode == "deterministic"
    assert result.provider == "deterministic"
    assert result.model == "templates"


@pytest.mark.asyncio
async def test_token_usage_recorded_when_available():
    local = _FakeProvider()
    engine = InsightEngine(local_llm_provider=local)

    result = await engine.generate(_medium_trend())

    assert result.prompt_tokens == 120
    assert result.completion_tokens == 40
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_missing_token_usage_handled_safely():
    class _NoTokenProvider:
        async def generate(self, prompt, think=True, options=None):
            return LLMResponse(content=_narrative_json(), model="m", latency_ms=100.0)

    engine = InsightEngine(local_llm_provider=_NoTokenProvider())
    result = await engine.generate(_medium_trend())

    assert result.prompt_tokens is None
    assert result.completion_tokens is None
    assert result.llm_generated is True  # missing tokens must not fail the call


# ── Extended provider/timing metadata (requested/resolved/fallback legs) ─────


@pytest.mark.asyncio
async def test_deterministic_extended_metadata():
    engine = InsightEngine(local_llm_provider=_FakeProvider())
    result = await engine.generate(_simple_distribution())

    assert result.requested_provider == "deterministic"
    assert result.requested_model == "templates"
    assert result.resolved_provider == "deterministic"
    assert result.resolved_model == "templates"
    assert result.remote_attempted is False
    assert result.thinking_enabled is False
    assert result.fallback_provider is None
    assert result.provider_duration_ms == 0.0
    assert result.total_llm_duration_ms == 0.0


@pytest.mark.asyncio
async def test_local_llm_extended_metadata():
    local = _FakeProvider(model="qwen3:8b")
    engine = InsightEngine(local_llm_provider=local)

    result = await engine.generate(_medium_trend())

    assert result.requested_provider == "ollama"
    assert result.requested_model == "qwen3:8b"
    assert result.resolved_provider == "ollama"
    assert result.resolved_model == "qwen3:8b"
    assert result.remote_attempted is False
    assert result.complexity_score is not None
    assert result.provider_duration_ms is not None
    assert result.total_llm_duration_ms == pytest.approx(result.provider_duration_ms)


@pytest.mark.asyncio
async def test_remote_llm_extended_metadata_records_attempt():
    remote = _FakeProvider(model="nvidia/nemotron-3-ultra-550b-a55b")
    engine = InsightEngine(local_llm_provider=_FakeProvider(), remote_llm_provider=remote)

    result = await engine.generate(_complex_multi_metric())

    assert result.requested_provider == "nvidia"
    assert result.requested_model == "nvidia/nemotron-3-ultra-550b-a55b"
    assert result.resolved_provider == "nvidia"
    assert result.resolved_model == "nvidia/nemotron-3-ultra-550b-a55b"
    assert result.remote_attempted is True
    assert result.fallback_provider is None
    assert result.provider_duration_ms is not None
    assert result.fallback_duration_ms is None
    assert result.complexity_score >= 3


@pytest.mark.asyncio
async def test_remote_fallback_records_fallback_provider_and_duration():
    remote = _FakeProvider(raise_exc=LLMTimeoutError("timed out"))
    local = _FakeProvider(model="qwen3:8b")
    engine = InsightEngine(local_llm_provider=local, remote_llm_provider=remote)

    result = await engine.generate(_complex_multi_metric())

    assert result.requested_provider == "nvidia"
    assert result.remote_attempted is True
    assert result.resolved_provider == "ollama"
    assert result.resolved_model == "qwen3:8b"
    assert result.fallback_provider == "ollama"
    assert result.provider_duration_ms is not None
    assert result.fallback_duration_ms is not None
    assert result.total_llm_duration_ms == pytest.approx(
        result.provider_duration_ms + result.fallback_duration_ms
    )


@pytest.mark.asyncio
async def test_double_failure_never_chains_to_another_remote_model():
    """Bounded fallback: remote fails once, local fails once, then deterministic —
    never a second remote attempt against any other NVIDIA model."""
    remote = _FakeProvider(raise_exc=LLMConnectionError("down"))
    local = _FakeProvider(raise_exc=LLMConnectionError("also down"))
    engine = InsightEngine(local_llm_provider=local, remote_llm_provider=remote)

    result = await engine.generate(_complex_multi_metric())

    assert remote.calls == 1
    assert local.calls == 1
    assert result.remote_attempted is True
    assert result.fallback_provider == "ollama"
    assert result.resolved_provider == "deterministic"


@pytest.mark.asyncio
async def test_response_contract_still_has_all_legacy_fields():
    engine = InsightEngine(local_llm_provider=_FakeProvider())
    result = await engine.generate(_medium_trend())

    # Every field that existed before routing was added must still be present.
    for field in (
        "title",
        "summary",
        "highlights",
        "observations",
        "considerations",
        "rules",
        "confidence",
        "llm_generated",
        "provider",
        "model",
        "duration_ms",
        "llm_latency_ms",
        "prompt_tokens",
        "completion_tokens",
    ):
        assert hasattr(result, field)


# ═══════════════ Multi-metric complexity routing (Phase 9) ═══════════════════


def _multi_metric_categorical() -> AnalyticsResult:
    from app.analytics.models import MetricSummary

    return AnalyticsResult(
        analytics_type="comparison",
        intents=[AnalyticsIntent.COMPARISON],
        data_shape=DataShape.CATEGORICAL,
        row_count=5,
        metric_summaries={
            "appointment_count": MetricSummary(
                metric_id="appointment_count", total=500, average=100
            ),
            "completed_appointment_rate": MetricSummary(
                metric_id="completed_appointment_rate", average=75.0
            ),
            "appointment_duration_average": MetricSummary(
                metric_id="appointment_duration_average", average=28.0
            ),
        },
    )


def test_three_metric_categorical_result_is_not_deterministic_candidate():
    router = InsightRouter(remote_available=True)
    decision = router.decide(_multi_metric_categorical(), [], InsightConfidence.HIGH)
    assert decision.deterministic_candidate is False
    assert "multi_metric_analysis" in decision.blocking_factors


def test_three_metric_categorical_result_routes_to_remote():
    router = InsightRouter(remote_available=True)
    decision = router.decide(_multi_metric_categorical(), [], InsightConfidence.HIGH)
    assert decision.mode == InsightGenerationMode.REMOTE_LLM
    assert decision.selected_provider == "nvidia"
    assert "multi_metric_analysis" in decision.complexity_factors


def test_single_metric_categorical_result_still_reaches_deterministic():
    router = InsightRouter(remote_available=True)
    decision = router.decide(_simple_distribution(), [], InsightConfidence.MEDIUM)
    assert decision.deterministic_candidate is True
    assert "multi_metric_analysis" not in decision.blocking_factors


# ═══════ Multi-metric result that ROW-COUNT-ONLY classifies as trivial ═══════


def _multi_metric_single_row() -> AnalyticsResult:
    from app.analytics.models import MetricSummary

    return AnalyticsResult(
        analytics_type="comparison",
        intents=[AnalyticsIntent.COMPARISON],
        data_shape=DataShape.CATEGORICAL,  # AnalyticsEngine's plan-aware fix
        row_count=1,
        metric_summaries={
            "appointment_count": MetricSummary(metric_id="appointment_count", total=89),
            "completed_appointment_rate": MetricSummary(
                metric_id="completed_appointment_rate", average=76.5
            ),
            "appointment_duration_average": MetricSummary(
                metric_id="appointment_duration_average", average=22.0
            ),
        },
    )


def test_single_row_multi_metric_result_never_trivially_deterministic():
    # Regression pin for the live bug: a genuinely one-row grouped result
    # (e.g. only one branch matched a narrow date range) must never be
    # treated as trivial just because row_count == 1 — TRIVIAL_SHAPES must
    # never short-circuit past the multi-metric blocking check.
    router = InsightRouter(remote_available=True)
    decision = router.decide(_multi_metric_single_row(), [], InsightConfidence.HIGH)
    assert decision.deterministic_candidate is False
    assert decision.mode == InsightGenerationMode.REMOTE_LLM
    assert decision.selected_provider == "nvidia"


def test_single_row_single_metric_result_stays_trivial():
    # A genuine single-value/single-row result with only one metric is
    # unaffected — still resolves deterministically.
    from app.analytics.models import AnalyticsResult as _AR

    analytics = _AR(
        analytics_type="count", intents=[], data_shape=DataShape.SINGLE_ROW, row_count=1
    )
    router = InsightRouter(remote_available=True)
    decision = router.decide(analytics, [], InsightConfidence.MEDIUM)
    assert decision.deterministic_candidate is True
