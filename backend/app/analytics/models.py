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


class ResultShape(StrEnum):
    """Business-semantic shape of the executed plan (not merely row layout)."""

    RAW_RECORD_ROWS = "raw_record_rows"
    GROUPED_ROWS = "grouped_rows"
    SCALAR_AGGREGATE = "scalar_aggregate"
    MULTI_METRIC_SCALAR_AGGREGATE = "multi_metric_scalar_aggregate"
    TIME_SERIES = "time_series"
    CATEGORICAL_GROUPED_RESULT = "categorical_grouped_result"
    EMPTY = "empty"


class DisplayableKPI(BaseModel):
    """A business KPI explicitly safe for user-facing presentation."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    value: Any
    format: str = "decimal"
    unit: str | None = None


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
    # Presentation metadata only: Türkçe etiket for `type`. `type` remains
    # the canonical value frontend/backend logic switches on.
    type_label: str | None = None


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
    # Presentation metadata only (AI-INTELLIGENCE-012): the Türkçe display
    # label for `metric_id`. `metric_id` remains the source of truth used by
    # code/tests; `metric_label` is what user-facing surfaces render.
    metric_label: str | None = None
    value: float | None = None
    format: str | None = None
    unit: str | None = None


class AnalyticsResult(BaseModel):
    """Structured, deterministic analytics computed from an executed SQL result.

    ``metrics`` holds calculated values (total, growth_rate, ...).
    ``insights`` holds pre-digested summary fields intended for a future
    LLM insight generator (trend, top_category, largest_change, ...).
    """

    model_config = ConfigDict(frozen=True)

    analytics_type: str
    # Presentation metadata only: Türkçe etiket for `analytics_type`.
    # `analytics_type` remains the canonical value.
    analytics_type_label: str | None = None
    intents: list[AnalyticsIntent] = Field(default_factory=list)
    data_shape: DataShape = DataShape.EMPTY
    metrics: dict[str, Any] = Field(default_factory=dict)
    insights: dict[str, Any] = Field(default_factory=dict)
    visualization: VisualizationRecommendation | None = None
    metric_column: str | None = None
    label_column: str | None = None
    row_count: int = 0
    technical_row_count: int = 0
    business_record_count: int | None = None
    result_shape: ResultShape = ResultShape.EMPTY
    aggregate_result: bool = False
    displayable_kpis: list[DisplayableKPI] = Field(default_factory=list)
    duration_ms: float = 0.0
    metric_summaries: dict[str, MetricSummary] = Field(default_factory=dict)

    # Reconciled endpoint/slope trend verdict — TIME_SERIES only, None otherwise.
    trend_metrics: TrendMetrics | None = None

    # Comparison-sufficiency metadata — CATEGORICAL only, None otherwise. Applies
    # generically to any grouping dimension (branch, doctor, department, ...).
    comparison_category_count: int | None = None
    comparison_sufficient: bool | None = None
    comparison_limitation_reason: str | None = None
