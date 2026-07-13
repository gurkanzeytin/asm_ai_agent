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


class AmbiguityResult(BaseModel):
    """Ambiguous ranking expression that cannot be mapped to SQL deterministically."""

    model_config = ConfigDict(frozen=True)

    matched_phrase: str
    question: str
    options: list[str] = Field(default_factory=list)


class QueryAnalysis(BaseModel):
    """Structured deterministic NLU analysis used to enrich schema retrieval.

    Pipeline stages captured for observability:
        original_query -> normalized_query stages -> rewritten_query
        -> expanded_query -> final_query (sent to SQL generation).

    ``normalized_query`` keeps its historical meaning: the fully rewritten and
    expanded natural-language query used for schema retrieval.
    """

    model_config = ConfigDict(frozen=True)

    original_query: str
    normalized_query: str
    rewritten_query: str = ""
    expanded_query: str = ""
    final_query: str = ""
    entities: list[DetectedEntity] = Field(default_factory=list)
    detected_dates: list[DateRange] = Field(default_factory=list)
    matched_synonyms: list[str] = Field(default_factory=list)
    detected_operations: list[str] = Field(default_factory=list)
    detected_limit: int | None = None
    detected_order: str | None = None
    is_ambiguous: bool = False
    ambiguity: AmbiguityResult | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
