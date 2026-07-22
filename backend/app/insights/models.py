"""Typed models for the Insight Intelligence Engine.

Separation of concerns: Analytics computes facts; Insights explain facts.
Confidence and business rules are always computed deterministically — the LLM
only supplies narrative text and never numbers, statistics, or confidence.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class InsightRule(StrEnum):
    """Deterministic business rule detected from the analytics object.

    HIGH_GROWTH/MODERATE_GROWTH/DECLINING/POSITIVE_TREND/NEGATIVE_TREND/
    STABLE_TREND are retained for enum stability but are no longer produced
    by ``InsightRulesEngine`` for TIME_SERIES data — they independently read
    growth_rate (first-vs-last) and trend_direction (half-vs-half mean),
    which could contradict each other (e.g. DECLINING + POSITIVE_TREND firing
    together). Replaced by the single, mutually exclusive
    CONSISTENT_UPWARD_TREND/CONSISTENT_DOWNWARD_TREND/MIXED_TREND_SIGNAL/
    FLAT_TREND/INSUFFICIENT_COMPLETE_PERIODS family below, derived from
    ``AnalyticsResult.trend_metrics.trend_consistency``.
    """

    HIGH_GROWTH = "HIGH_GROWTH"
    MODERATE_GROWTH = "MODERATE_GROWTH"
    DECLINING = "DECLINING"
    POSITIVE_TREND = "POSITIVE_TREND"
    NEGATIVE_TREND = "NEGATIVE_TREND"
    STABLE_TREND = "STABLE_TREND"
    DOMINANT_CATEGORY = "DOMINANT_CATEGORY"
    BALANCED_DISTRIBUTION = "BALANCED_DISTRIBUTION"
    OUTLIER_DETECTED = "OUTLIER_DETECTED"
    SINGLE_METRIC = "SINGLE_METRIC"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

    # Reconciled trend rules (mutually exclusive per analytics result).
    CONSISTENT_UPWARD_TREND = "CONSISTENT_UPWARD_TREND"
    CONSISTENT_DOWNWARD_TREND = "CONSISTENT_DOWNWARD_TREND"
    MIXED_TREND_SIGNAL = "MIXED_TREND_SIGNAL"
    FLAT_TREND = "FLAT_TREND"
    INSUFFICIENT_COMPLETE_PERIODS = "INSUFFICIENT_COMPLETE_PERIODS"
    PARTIAL_PERIOD_EXCLUDED = "PARTIAL_PERIOD_EXCLUDED"

    # Comparison-sufficiency rule.
    SINGLE_CATEGORY_COMPARISON = "SINGLE_CATEGORY_COMPARISON"


class InsightConfidence(StrEnum):
    """Deterministically computed confidence level (never LLM-generated)."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class InsightNarrative(BaseModel):
    """Narrative fields of an insight — the only part an LLM may produce.

    Also used to validate/parse the LLM's JSON output, so any structural
    deviation is rejected before it can reach the pipeline.
    """

    title: str = Field(default="", max_length=200)
    summary: str = Field(default="")
    highlights: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    considerations: list[str] = Field(default_factory=list)


class InsightResult(BaseModel):
    """Structured executive insight grounded in deterministic analytics."""

    model_config = ConfigDict(frozen=True)

    title: str
    summary: str
    highlights: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    considerations: list[str] = Field(default_factory=list)
    rules: list[InsightRule] = Field(default_factory=list)
    confidence: InsightConfidence = InsightConfidence.LOW
    llm_generated: bool = False
    provider: str = "deterministic"
    model: str = "templates"
    duration_ms: float = 0.0
    llm_latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    routing_mode: str | None = None
    routing_reason: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    remote_data_policy: str | None = None
    attempts: int = 0

    # Extended routing/provider diagnostics (Part 6). All optional/defaulted so
    # the legacy single-provider path and existing callers are unaffected.
    requested_provider: str | None = Field(
        default=None, description="Provider the router selected before any fallback."
    )
    requested_model: str | None = Field(
        default=None, description="Model name of the originally selected provider."
    )
    resolved_provider: str | None = Field(
        default=None,
        description="Provider that actually produced this result (mirrors `provider`).",
    )
    resolved_model: str | None = Field(
        default=None, description="Model that actually produced this result (mirrors `model`)."
    )
    complexity_score: int | None = Field(
        default=None, description="Computed complexity score behind the routing decision."
    )
    thinking_enabled: bool = Field(
        default=False, description="Whether reasoning/thinking mode was requested for this call."
    )
    remote_attempted: bool = Field(
        default=False, description="Whether the remote (NVIDIA) leg was actually invoked."
    )
    fallback_provider: str | None = Field(
        default=None, description="Provider used for the one-shot fallback attempt, if any."
    )
    provider_duration_ms: float | None = Field(
        default=None, description="Wall-clock duration of the primary provider attempt."
    )
    fallback_duration_ms: float | None = Field(
        default=None, description="Wall-clock duration of the fallback provider attempt, if any."
    )
    total_llm_duration_ms: float | None = Field(
        default=None, description="Sum of provider_duration_ms and fallback_duration_ms."
    )
