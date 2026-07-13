"""Regression tests for AI-ANALYTICS-002 — Insight Intelligence Engine.

Rules and confidence are deterministic (no LLM). The LLM only supplies
narrative text and is faked in these tests — no network, no real provider.
"""

import json

import pytest

from app.agent.nodes.generate_insights import GenerateInsightsNode
from app.agent.state import AgentState
from app.analytics.models import (
    AnalyticsResult,
    DataShape,
    VisualizationRecommendation,
    VisualizationType,
)
from app.insights.insight_engine import InsightEngine
from app.insights.models import InsightConfidence, InsightRule
from app.insights.prompt_builder import InsightPromptBuilder
from app.insights.rules_engine import InsightRulesEngine
from app.insights.templates import INSUFFICIENT_EVIDENCE_SUMMARY
from app.llm.schemas import LLMResponse


def _analytics(**overrides) -> AnalyticsResult:
    base = dict(
        analytics_type="trend",
        intents=[],
        data_shape=DataShape.TIME_SERIES,
        metrics={
            "count": 6,
            "total": 1587.0,
            "average": 264.5,
            "median": 240.0,
            "minimum": 201.0,
            "maximum": 412.0,
            "highest_value": 412.0,
            "lowest_value": 201.0,
            "growth_rate": 18.4,
            "trend_direction": "upward",
            "largest_change": "2026-05",
        },
        insights={"trend": "upward", "growth_rate": 18.4},
        visualization=VisualizationRecommendation(
            type=VisualizationType.LINE_CHART, reason="Time-series data detected"
        ),
        row_count=6,
    )
    base.update(overrides)
    return AnalyticsResult(**base)


def _empty_analytics() -> AnalyticsResult:
    return AnalyticsResult(
        analytics_type="none",
        data_shape=DataShape.EMPTY,
        metrics={"count": 0},
        row_count=0,
    )


class FakeLLMProvider:
    """Deterministic fake provider returning a fixed JSON narrative."""

    def __init__(self, content: str | None = None, fail: bool = False):
        self.fail = fail
        self.prompts: list[str] = []
        self.content = content or json.dumps(
            {
                "title": "Appointment Trend Analysis",
                "summary": "Appointments increased steadily during the period.",
                "highlights": ["Growth reached 18.4%"],
                "observations": ["The largest increase occurred in 2026-05"],
                "considerations": [],
                "confidence": "LOW",  # must be ignored — confidence is computed
            }
        )

    async def generate(self, prompt, think=True, options=None):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("provider down")
        return LLMResponse(
            content=self.content,
            model="fake-model",
            latency_ms=12.5,
            prompt_tokens=200,
            completion_tokens=80,
        )


# ── Part 2: Rule engine ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("growth_rate", "expected_rule"),
    [
        (18.4, InsightRule.HIGH_GROWTH),
        (15.1, InsightRule.HIGH_GROWTH),
        (15.0, InsightRule.MODERATE_GROWTH),
        (7.0, InsightRule.MODERATE_GROWTH),
        (0.0, InsightRule.MODERATE_GROWTH),
        (-4.2, InsightRule.DECLINING),
    ],
)
def test_growth_rules(growth_rate, expected_rule):
    analytics = _analytics(
        metrics={**_analytics().metrics, "growth_rate": growth_rate}
    )

    rules = InsightRulesEngine().evaluate(analytics)

    assert expected_rule in rules


@pytest.mark.parametrize(
    ("trend", "expected_rule"),
    [
        ("upward", InsightRule.POSITIVE_TREND),
        ("downward", InsightRule.NEGATIVE_TREND),
        ("stable", InsightRule.STABLE_TREND),
    ],
)
def test_trend_rules(trend, expected_rule):
    analytics = _analytics(metrics={**_analytics().metrics, "trend_direction": trend})

    assert expected_rule in InsightRulesEngine().evaluate(analytics)


def test_dominant_category_rule():
    analytics = _analytics(
        analytics_type="comparison",
        data_shape=DataShape.CATEGORICAL,
        metrics={
            "count": 3,
            "total": 100.0,
            "average": 33.3,
            "maximum": 60.0,
            "top_category": "Psikiyatri",
            "distribution": {"Psikiyatri": 60.0, "Kardiyoloji": 25.0, "Dermatoloji": 15.0},
        },
    )

    rules = InsightRulesEngine().evaluate(analytics)

    assert InsightRule.DOMINANT_CATEGORY in rules
    assert InsightRule.BALANCED_DISTRIBUTION not in rules
    assert InsightRule.OUTLIER_DETECTED in rules  # 60 > 1.5 * 33.3


def test_balanced_distribution_rule():
    analytics = _analytics(
        analytics_type="distribution",
        data_shape=DataShape.CATEGORICAL,
        metrics={
            "count": 3,
            "total": 99.0,
            "average": 33.0,
            "maximum": 35.0,
            "top_category": "A",
            "distribution": {"A": 35.0, "B": 33.0, "C": 32.0},
        },
    )

    rules = InsightRulesEngine().evaluate(analytics)

    assert InsightRule.BALANCED_DISTRIBUTION in rules
    assert InsightRule.DOMINANT_CATEGORY not in rules
    assert InsightRule.OUTLIER_DETECTED not in rules


def test_single_metric_rule():
    analytics = _analytics(
        analytics_type="summary",
        data_shape=DataShape.SINGLE_VALUE,
        metrics={"count": 1, "total": 42.0},
        row_count=1,
    )

    assert InsightRule.SINGLE_METRIC in InsightRulesEngine().evaluate(analytics)


def test_empty_analytics_yields_insufficient_evidence():
    rules = InsightRulesEngine().evaluate(_empty_analytics())

    assert rules == [InsightRule.INSUFFICIENT_EVIDENCE]


def test_rules_are_deterministic():
    engine = InsightRulesEngine()
    analytics = _analytics()

    assert engine.evaluate(analytics) == engine.evaluate(analytics)


# ── Part 5: Confidence model ──────────────────────────────────────────────────


def test_confidence_high_when_analytics_complete():
    engine = InsightRulesEngine()
    analytics = _analytics()
    rules = engine.evaluate(analytics)

    assert engine.compute_confidence(analytics, rules) == InsightConfidence.HIGH


def test_confidence_medium_when_metrics_missing():
    engine = InsightRulesEngine()
    metrics = dict(_analytics().metrics)
    metrics["growth_rate"] = None  # e.g. first value was zero
    analytics = _analytics(metrics=metrics)
    rules = engine.evaluate(analytics)

    assert engine.compute_confidence(analytics, rules) == InsightConfidence.MEDIUM


def test_confidence_low_on_empty_analytics():
    engine = InsightRulesEngine()
    analytics = _empty_analytics()
    rules = engine.evaluate(analytics)

    assert engine.compute_confidence(analytics, rules) == InsightConfidence.LOW


# ── Part 3: Prompt construction ───────────────────────────────────────────────


def test_prompt_contains_only_analytics_rules_and_visualization():
    builder = InsightPromptBuilder()
    analytics = _analytics()

    prompt = builder.build(analytics, [InsightRule.HIGH_GROWTH, InsightRule.POSITIVE_TREND])

    assert "18.4" in prompt
    assert "HIGH_GROWTH, POSITIVE_TREND" in prompt
    assert "LINE_CHART" in prompt
    # Forbidden content: SQL, schema, raw rows are never included.
    assert "SELECT" not in prompt.upper() or "SQL" in prompt  # prompt mentions no queries
    assert "randevular" not in prompt  # no table names
    assert "rows" not in json.dumps(builder.analytics_payload(analytics))


def test_prompt_payload_truncates_rankings():
    builder = InsightPromptBuilder()
    top = [{"label": f"C{i}", "value": float(i)} for i in range(10)]
    analytics = _analytics(
        data_shape=DataShape.CATEGORICAL,
        metrics={**_analytics().metrics, "top_n": top},
    )

    payload = builder.analytics_payload(analytics)

    assert len(payload["top_categories"]) == 5
    assert "top_n" not in payload["metrics"]


# ── Part 4/6: Engine output structure & safety ────────────────────────────────


@pytest.mark.asyncio
async def test_engine_generates_structured_insight_via_llm():
    provider = FakeLLMProvider()
    engine = InsightEngine(llm_provider=provider)

    result = await engine.generate(_analytics())

    assert result.title == "Appointment Trend Analysis"
    assert result.summary
    assert result.highlights == ["Growth reached 18.4%"]
    assert result.llm_generated is True
    assert result.model == "fake-model"
    assert set(result.rules) == {InsightRule.HIGH_GROWTH, InsightRule.POSITIVE_TREND}
    assert result.confidence == InsightConfidence.HIGH  # computed, not the LLM's "LOW"
    assert result.prompt_tokens == 200
    assert result.completion_tokens == 80
    assert result.llm_latency_ms == 12.5


@pytest.mark.asyncio
async def test_engine_ignores_llm_confidence_field():
    provider = FakeLLMProvider()
    engine = InsightEngine(llm_provider=provider)

    result = await engine.generate(_analytics())

    # Fake LLM claims "LOW"; deterministic model computes HIGH.
    assert result.confidence == InsightConfidence.HIGH


@pytest.mark.asyncio
async def test_engine_handles_fenced_json_output():
    content = "```json\n" + json.dumps({"title": "T", "summary": "S"}) + "\n```"
    engine = InsightEngine(llm_provider=FakeLLMProvider(content=content))

    result = await engine.generate(_analytics())

    assert result.title == "T"
    assert result.summary == "S"
    assert result.llm_generated is True


@pytest.mark.asyncio
async def test_engine_falls_back_to_templates_on_llm_failure():
    engine = InsightEngine(llm_provider=FakeLLMProvider(fail=True))

    result = await engine.generate(_analytics())

    assert result.llm_generated is False
    assert result.provider == "deterministic"
    assert result.summary  # grounded template narrative
    assert "18.4" in " ".join(result.highlights)
    assert result.confidence == InsightConfidence.HIGH


@pytest.mark.asyncio
async def test_engine_falls_back_on_invalid_llm_json():
    engine = InsightEngine(llm_provider=FakeLLMProvider(content="not json at all"))

    result = await engine.generate(_analytics())

    assert result.llm_generated is False
    assert result.summary


@pytest.mark.asyncio
async def test_engine_empty_analytics_states_insufficient_evidence_without_llm():
    provider = FakeLLMProvider()
    engine = InsightEngine(llm_provider=provider)

    result = await engine.generate(_empty_analytics())

    assert result.summary == INSUFFICIENT_EVIDENCE_SUMMARY
    assert result.confidence == InsightConfidence.LOW
    assert result.rules == [InsightRule.INSUFFICIENT_EVIDENCE]
    assert result.llm_generated is False
    assert provider.prompts == []  # LLM must not be called without evidence


@pytest.mark.asyncio
async def test_engine_without_provider_uses_templates():
    engine = InsightEngine(llm_provider=None)

    result = await engine.generate(_analytics())

    assert result.llm_generated is False
    assert result.highlights
    assert all(isinstance(item, str) for item in result.highlights)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "analytics",
    [
        _analytics(),  # growth / upward trend
        _analytics(  # decline
            metrics={
                **_analytics().metrics,
                "growth_rate": -12.0,
                "trend_direction": "downward",
            }
        ),
        _analytics(  # stable
            metrics={**_analytics().metrics, "growth_rate": 1.0, "trend_direction": "stable"}
        ),
        _analytics(  # comparison / ranking
            analytics_type="comparison",
            data_shape=DataShape.CATEGORICAL,
            metrics={
                "count": 3,
                "total": 360.0,
                "average": 120.0,
                "maximum": 180.0,
                "top_category": "Psikiyatri",
                "distribution": {"Psikiyatri": 50.0, "Kardiyoloji": 33.3, "Dermatoloji": 16.7},
            },
        ),
        _analytics(  # single metric
            analytics_type="summary",
            data_shape=DataShape.SINGLE_VALUE,
            metrics={"count": 1, "total": 42.0},
            row_count=1,
        ),
    ],
)
async def test_engine_always_returns_valid_structure(analytics):
    result = await InsightEngine(llm_provider=None).generate(analytics)

    assert result.title
    assert result.summary
    assert isinstance(result.highlights, list)
    assert isinstance(result.observations, list)
    assert result.confidence in (
        InsightConfidence.HIGH,
        InsightConfidence.MEDIUM,
        InsightConfidence.LOW,
    )


# ── Pipeline integration ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_insights_node_populates_state():
    node = GenerateInsightsNode(InsightEngine(llm_provider=FakeLLMProvider()))
    state = AgentState(question="Son 6 ayı analiz et", analytics=_analytics())

    result = await node.execute(state)

    assert result.insights is not None
    assert result.insights.llm_generated is True
    assert "generate_insights" in result.completed_nodes
    assert "generate_insights" in result.node_timings
    assert result.errors == []


@pytest.mark.asyncio
async def test_generate_insights_node_skips_without_analytics():
    node = GenerateInsightsNode(InsightEngine(llm_provider=FakeLLMProvider()))
    state = AgentState(question="Doktorları listele")

    result = await node.execute(state)

    assert result.insights is None
    assert "generate_insights" not in result.completed_nodes
    assert result.errors == []


@pytest.mark.asyncio
async def test_generate_insights_node_failure_is_non_fatal():
    class ExplodingEngine:
        async def generate(self, analytics):
            raise RuntimeError("boom")

    node = GenerateInsightsNode(ExplodingEngine())
    state = AgentState(question="Analiz et", analytics=_analytics())

    result = await node.execute(state)

    assert result.insights is None
    assert result.errors == []
    assert "generate_insights" in result.node_timings
