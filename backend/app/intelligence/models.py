"""Typed models for the Observation Engine (Layer 4 of the response intelligence).

Observations highlight noteworthy, evidence-based facts. They are never
recommendations, decisions, or medical advice, and they are derived exclusively
from analytics and insight metadata — never from raw SQL or raw rows.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.insights.models import InsightConfidence


class ObservationCategory(StrEnum):
    """Classification of what an observation is about."""

    GROWTH = "growth"
    TREND = "trend"
    DISTRIBUTION = "distribution"
    RANKING = "ranking"
    CHANGE = "change"
    VOLUME = "volume"
    DATA_QUALITY = "data_quality"


class Observation(BaseModel):
    """A single noteworthy, evidence-based fact."""

    model_config = ConfigDict(frozen=True)

    rule: str = Field(..., description="Deterministic rule that produced this observation.")
    category: ObservationCategory
    text: str = Field(..., description="Human-readable observation wording.")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Metric values from the analytics object that ground this observation.",
    )


class ObservationResult(BaseModel):
    """Structured output of the Observation Engine (response Layer 4)."""

    model_config = ConfigDict(frozen=True)

    observations: list[Observation] = Field(default_factory=list)
    confidence: InsightConfidence = InsightConfidence.LOW
    llm_worded: bool = Field(
        default=False,
        description="Whether the LLM reworded the deterministic observation texts.",
    )
    rule_count: int = 0
    duration_ms: float = 0.0
    llm_latency_ms: float | None = None
