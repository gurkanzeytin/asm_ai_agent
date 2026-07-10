from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DetectedEntity(BaseModel):
    """Rule-based domain entity detected in a natural-language query."""

    model_config = ConfigDict(frozen=True)

    entity_type: str
    canonical: str
    text: str
    normalized_text: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DateRange(BaseModel):
    """Deterministic date range extracted from temporal language."""

    model_config = ConfigDict(frozen=True)

    expression: str
    start_date: date
    end_date: date
    granularity: str


class QueryAnalysis(BaseModel):
    """Structured deterministic NLU analysis used to enrich schema retrieval."""

    model_config = ConfigDict(frozen=True)

    original_query: str
    normalized_query: str
    entities: list[DetectedEntity] = Field(default_factory=list)
    detected_dates: list[DateRange] = Field(default_factory=list)
    matched_synonyms: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
