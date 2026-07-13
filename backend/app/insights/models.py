"""Typed models for the Insight Intelligence Engine.

Separation of concerns: Analytics computes facts; Insights explain facts.
Confidence and business rules are always computed deterministically — the LLM
only supplies narrative text and never numbers, statistics, or confidence.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class InsightRule(StrEnum):
    """Deterministic business rule detected from the analytics object."""

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
