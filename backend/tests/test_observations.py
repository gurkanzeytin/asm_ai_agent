"""Regression tests for AI-INTELLIGENCE-001 — Layered Response Intelligence.

The Observation Engine is deterministic; the LLM (faked here) may only reword
texts and is rejected whenever it changes facts, counts, or uses directive
language.
"""

import json

import pytest

from app.agent.nodes.generate_observations import GenerateObservationsNode
from app.agent.state import AgentState
from app.analytics.models import AnalyticsResult, DataShape
from app.insights.models import InsightConfidence, InsightResult, InsightRule
from app.intelligence.models import ObservationCategory
from app.intelligence.observation_engine import ObservationEngine
from app.intelligence.observation_rules import build_observations
from app.llm.schemas import LLMResponse
from app.schemas.report import ObservationsSchema, ReportResponse


def _analytics(**overrides) -> AnalyticsResult:
    base = dict(
        analytics_type="trend",
        data_shape=DataShape.TIME_SERIES,
        metrics={
            "count": 6,
            "total": 1587.0,
            "average": 264.5,
            "highest_value": 412.0,
            "lowest_value": 201.0,
            "growth_rate": 18.4,
            "trend_direction": "upward",
            "largest_change": "2026-05",
        },
        row_count=6,
    )
    base.update(overrides)
    return AnalyticsResult(**base)


def _categorical_analytics(**metric_overrides) -> AnalyticsResult:
    metrics = {
        "count": 3,
        "total": 360.0,
        "average": 120.0,
        "maximum": 180.0,
        "highest_value": 180.0,
        "lowest_value": 60.0,
        "top_category": "Psikiyatri",
        "distribution": {"Psikiyatri": 50.0, "Kardiyoloji": 33.3, "Dermatoloji": 16.7},
    }
    metrics.update(metric_overrides)
    return AnalyticsResult(
        analytics_type="comparison",
        data_shape=DataShape.CATEGORICAL,
        metrics=metrics,
        row_count=3,
    )


def _empty_analytics() -> AnalyticsResult:
    return AnalyticsResult(
        analytics_type="none", data_shape=DataShape.EMPTY, metrics={"count": 0}, row_count=0
    )


class FakeLLMProvider:
    def __init__(self, content: str, fail: bool = False):
        self.content = content
        self.fail = fail
        self.prompts: list[str] = []

    async def generate(self, prompt, think=True, options=None):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("provider down")
        return LLMResponse(content=self.content, model="fake-model", latency_ms=9.0)


# ── Observation rules ─────────────────────────────────────────────────────────


def test_high_growth_observation():
    observations = build_observations(_analytics(), [InsightRule.HIGH_GROWTH])

    texts = [obs.text for obs in observations]
    assert "Sustained growth detected: values increased by 18.4%." in texts
    growth = next(obs for obs in observations if obs.rule == "HIGH_GROWTH")
    assert growth.category == ObservationCategory.GROWTH
    assert growth.evidence == {"growth_rate": 18.4}


def test_declining_trend_observations():
    analytics = _analytics(
        metrics={
            **_analytics().metrics,
            "growth_rate": -12.0,
            "trend_direction": "downward",
        }
    )

    observations = build_observations(
        analytics, [InsightRule.DECLINING, InsightRule.NEGATIVE_TREND]
    )

    texts = [obs.text for obs in observations]
    assert "A downward trend is visible." in texts
    assert any("-12.0%" in text for text in texts)


def test_stable_trend_observation():
    observations = build_observations(_analytics(), [InsightRule.STABLE_TREND])

    assert any(obs.text == "Values have remained stable over the period." for obs in observations)


def test_dominant_category_observation():
    analytics = _categorical_analytics(
        distribution={"Psikiyatri": 60.0, "Kardiyoloji": 25.0, "Dermatoloji": 15.0}
    )

    observations = build_observations(analytics, [InsightRule.DOMINANT_CATEGORY])

    texts = [obs.text for obs in observations]
    assert "One category clearly dominates: 'Psikiyatri' holds the largest share." in texts
    assert "'Psikiyatri' has the highest volume in this result." in texts


def test_balanced_distribution_observation():
    observations = build_observations(
        _categorical_analytics(), [InsightRule.BALANCED_DISTRIBUTION]
    )

    assert any(
        obs.text == "No significant imbalance detected across categories."
        for obs in observations
    )


def test_single_metric_observation():
    analytics = AnalyticsResult(
        analytics_type="summary",
        data_shape=DataShape.SINGLE_VALUE,
        metrics={"count": 1, "total": 42.0},
        row_count=1,
    )

    observations = build_observations(analytics, [InsightRule.SINGLE_METRIC])

    assert any("42.0" in obs.text for obs in observations)


def test_significant_spread_observation():
    observations = build_observations(_categorical_analytics(), [])

    assert any(obs.rule == "SIGNIFICANT_SPREAD" for obs in observations)
    spread = next(obs for obs in observations if obs.rule == "SIGNIFICANT_SPREAD")
    assert "may deserve attention" in spread.text


def test_empty_analytics_yields_single_data_quality_observation():
    observations = build_observations(
        _empty_analytics(), [InsightRule.INSUFFICIENT_EVIDENCE]
    )

    assert len(observations) == 1
    assert observations[0].category == ObservationCategory.DATA_QUALITY


def test_no_directive_language_in_any_template_observation():
    all_rules = [rule for rule in InsightRule]
    for analytics in (_analytics(), _categorical_analytics()):
        for obs in build_observations(analytics, all_rules):
            lowered = obs.text.lower()
            for forbidden in ("must", "should", "needs to", "recommend"):
                assert forbidden not in lowered, obs.text


# ── Observation engine ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_reuses_insight_rules_and_confidence():
    insights = InsightResult(
        title="T",
        summary="S",
        rules=[InsightRule.HIGH_GROWTH, InsightRule.POSITIVE_TREND],
        confidence=InsightConfidence.HIGH,
    )
    engine = ObservationEngine()

    result = await engine.generate(_analytics(), insights)

    assert result.confidence == InsightConfidence.HIGH
    assert result.rule_count == 2
    assert result.llm_worded is False
    assert any(obs.rule == "HIGH_GROWTH" for obs in result.observations)


@pytest.mark.asyncio
async def test_engine_computes_rules_when_insights_missing():
    engine = ObservationEngine()

    result = await engine.generate(_analytics(), None)

    assert result.rule_count > 0
    assert result.observations
    assert result.confidence == InsightConfidence.HIGH


@pytest.mark.asyncio
async def test_engine_empty_analytics_is_low_confidence():
    engine = ObservationEngine()

    result = await engine.generate(_empty_analytics(), None)

    assert result.confidence == InsightConfidence.LOW
    assert len(result.observations) == 1
    assert result.observations[0].category == ObservationCategory.DATA_QUALITY


@pytest.mark.asyncio
async def test_engine_is_deterministic():
    engine = ObservationEngine()

    first = await engine.generate(_categorical_analytics(), None)
    second = await engine.generate(_categorical_analytics(), None)

    assert [obs.text for obs in first.observations] == [obs.text for obs in second.observations]
    assert first.confidence == second.confidence


# ── LLM rewording guardrails ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_rewording_applies_when_valid():
    engine_no_llm = ObservationEngine()
    baseline = await engine_no_llm.generate(_analytics(), None)
    reworded_texts = [f"Reworded: {obs.text}" for obs in baseline.observations]
    provider = FakeLLMProvider(json.dumps({"observations": reworded_texts}))
    engine = ObservationEngine(llm_provider=provider, use_llm_wording=True)

    result = await engine.generate(_analytics(), None)

    assert result.llm_worded is True
    assert [obs.text for obs in result.observations] == reworded_texts
    assert result.llm_latency_ms == 9.0
    # Rules and evidence are untouched by rewording.
    assert [obs.rule for obs in result.observations] == [
        obs.rule for obs in baseline.observations
    ]


@pytest.mark.asyncio
async def test_llm_rewording_rejected_on_changed_numbers():
    provider = FakeLLMProvider(
        json.dumps({"observations": ["Growth reached 99.9% which is amazing"] * 5})
    )
    engine = ObservationEngine(llm_provider=provider, use_llm_wording=True)

    result = await engine.generate(_analytics(), None)

    assert result.llm_worded is False  # falls back to deterministic templates
    assert any("18.4%" in obs.text for obs in result.observations)


@pytest.mark.asyncio
async def test_llm_rewording_rejected_on_directive_language():
    engine_no_llm = ObservationEngine()
    baseline = await engine_no_llm.generate(_analytics(), None)
    texts = [obs.text + " You should act now." for obs in baseline.observations]
    provider = FakeLLMProvider(json.dumps({"observations": texts}))
    engine = ObservationEngine(llm_provider=provider, use_llm_wording=True)

    result = await engine.generate(_analytics(), None)

    assert result.llm_worded is False


@pytest.mark.asyncio
async def test_llm_rewording_rejected_on_count_mismatch():
    provider = FakeLLMProvider(json.dumps({"observations": ["only one"]}))
    engine = ObservationEngine(llm_provider=provider, use_llm_wording=True)

    result = await engine.generate(_analytics(), None)

    assert result.llm_worded is False
    assert len(result.observations) > 1


@pytest.mark.asyncio
async def test_llm_failure_keeps_deterministic_observations():
    provider = FakeLLMProvider("", fail=True)
    engine = ObservationEngine(llm_provider=provider, use_llm_wording=True)

    result = await engine.generate(_analytics(), None)

    assert result.llm_worded is False
    assert result.observations


@pytest.mark.asyncio
async def test_llm_not_called_when_wording_disabled():
    provider = FakeLLMProvider(json.dumps({"observations": []}))
    engine = ObservationEngine(llm_provider=provider, use_llm_wording=False)

    await engine.generate(_analytics(), None)

    assert provider.prompts == []


# ── Pipeline integration & API schema ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_observations_node_populates_state():
    node = GenerateObservationsNode(ObservationEngine())
    state = AgentState(question="Analiz et", analytics=_analytics())

    result = await node.execute(state)

    assert result.observations is not None
    assert result.observations.observations
    assert "generate_observations" in result.completed_nodes
    assert "generate_observations" in result.node_timings
    assert result.errors == []


@pytest.mark.asyncio
async def test_generate_observations_node_skips_without_analytics():
    node = GenerateObservationsNode(ObservationEngine())
    state = AgentState(question="Doktorları listele")

    result = await node.execute(state)

    assert result.observations is None
    assert "generate_observations" not in result.completed_nodes
    assert result.errors == []


@pytest.mark.asyncio
async def test_generate_observations_node_failure_is_non_fatal():
    class ExplodingEngine:
        async def generate(self, analytics, insights=None):
            raise RuntimeError("boom")

    node = GenerateObservationsNode(ExplodingEngine())
    state = AgentState(question="Analiz et", analytics=_analytics())

    result = await node.execute(state)

    assert result.observations is None
    assert result.errors == []


def test_report_response_exposes_independent_layers():
    """Layers must be independently optional and addressable on the API schema."""
    fields = ReportResponse.model_fields
    for layer in ("query_result", "analytics", "insights", "observations", "visualization"):
        assert layer in fields
        assert not fields[layer].is_required()

    schema = ObservationsSchema(
        observations=[
            {
                "rule": "HIGH_GROWTH",
                "category": "growth",
                "text": "Sustained growth detected: values increased by 18.4%.",
                "evidence": {"growth_rate": 18.4},
            }
        ],
        confidence="HIGH",
    )
    payload = schema.model_dump()
    assert payload["observations"][0]["evidence"] == {"growth_rate": 18.4}
    assert payload["llm_worded"] is False
