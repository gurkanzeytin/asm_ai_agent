"""Typed models for the Analytics Intelligence Layer.

All models are frozen Pydantic DTOs. The analytics layer is fully deterministic:
no model in this package ever carries LLM output.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsIntent(StrEnum):
    """Analytical intent detected from the natural-language question."""

    TREND = "trend"
    COMPARISON = "comparison"
    GROWTH_RATE = "growth_rate"
    PERCENTAGE_CHANGE = "percentage_change"
    RANKING = "ranking"
    DISTRIBUTION = "distribution"
    AVERAGE = "average"
    MEDIAN = "median"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    TIME_SERIES = "time_series"
    CORRELATION = "correlation"  # future — detected but not calculated yet
    FORECAST = "forecast"  # future placeholder — detected but not calculated yet
    GENERAL = "general"


class DataShape(StrEnum):
    """Structural classification of an SQL result set."""

    EMPTY = "empty"
    SINGLE_VALUE = "single_value"
    SINGLE_ROW = "single_row"
    TIME_SERIES = "time_series"
    CATEGORICAL = "categorical"
    TABULAR = "tabular"


class VisualizationType(StrEnum):
    """Supported visualization recommendations (metadata only, no rendering)."""

    CARD = "CARD"
    TABLE = "TABLE"
    BAR_CHART = "BAR_CHART"
    LINE_CHART = "LINE_CHART"
    PIE_CHART = "PIE_CHART"


class VisualizationRecommendation(BaseModel):
    """Structured visualization decision for the frontend to consume later."""

    model_config = ConfigDict(frozen=True)

    type: VisualizationType
    reason: str


class AnalyticsResult(BaseModel):
    """Structured, deterministic analytics computed from an executed SQL result.

    ``metrics`` holds calculated values (total, growth_rate, ...).
    ``insights`` holds pre-digested summary fields intended for a future
    LLM insight generator (trend, top_category, largest_change, ...).
    """

    model_config = ConfigDict(frozen=True)

    analytics_type: str
    intents: list[AnalyticsIntent] = Field(default_factory=list)
    data_shape: DataShape = DataShape.EMPTY
    metrics: dict[str, Any] = Field(default_factory=dict)
    insights: dict[str, Any] = Field(default_factory=dict)
    visualization: VisualizationRecommendation | None = None
    metric_column: str | None = None
    label_column: str | None = None
    row_count: int = 0
    duration_ms: float = 0.0
