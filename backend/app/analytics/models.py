"""Typed models for the Analytics Intelligence Layer.

All models are frozen Pydantic DTOs. The analytics layer is fully deterministic:
no model in this package ever carries LLM output.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.trend_analysis import TrendMetrics


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
    GROUPED_BAR_CHART = "GROUPED_BAR_CHART"
    MULTI_SERIES_BAR_CHART = "MULTI_SERIES_BAR_CHART"


class VisualizationRecommendation(BaseModel):
    """Structured visualization decision for the frontend to consume later."""

    model_config = ConfigDict(frozen=True)

    type: VisualizationType
    reason: str


class MetricSummary(BaseModel):
    """Per-metric aggregate summary, keyed by metric catalog id in
    `AnalyticsResult.metric_summaries`. Additive/independent of `metric_column`
    — computed only when a QueryPlan with >=1 planned metric and a matching
    metric-alias map are available; never replaces the single-metric-column
    heuristic `_profile_columns` already uses."""

    model_config = ConfigDict(frozen=True)

    metric_id: str
    total: float | None = None
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    top_dimension: str | None = None
    bottom_dimension: str | None = None


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
    metric_summaries: dict[str, MetricSummary] = Field(default_factory=dict)

    # Reconciled endpoint/slope trend verdict — TIME_SERIES only, None otherwise.
    trend_metrics: TrendMetrics | None = None

    # Comparison-sufficiency metadata — CATEGORICAL only, None otherwise. Applies
    # generically to any grouping dimension (branch, doctor, department, ...).
    comparison_category_count: int | None = None
    comparison_sufficient: bool | None = None
    comparison_limitation_reason: str | None = None
