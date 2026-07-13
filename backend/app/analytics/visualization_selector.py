"""Rule-based visualization decision engine.

Selects the most appropriate visualization type for an analytics result.
Returns structured metadata only — no chart rendering, no frontend work.
"""

import logging

from app.analytics.models import (
    AnalyticsIntent,
    DataShape,
    VisualizationRecommendation,
    VisualizationType,
)

logger = logging.getLogger(__name__)


class VisualizationSelector:
    """Deterministic mapping from data shape + analytical intents to a visualization."""

    def __init__(
        self,
        large_result_threshold: int = 30,
        max_pie_categories: int = 6,
    ) -> None:
        self.large_result_threshold = large_result_threshold
        self.max_pie_categories = max_pie_categories

    def select(
        self,
        data_shape: DataShape,
        intents: list[AnalyticsIntent],
        row_count: int,
        category_count: int = 0,
    ) -> VisualizationRecommendation:
        if data_shape == DataShape.EMPTY:
            return VisualizationRecommendation(
                type=VisualizationType.TABLE, reason="Empty result set"
            )

        if data_shape == DataShape.SINGLE_VALUE:
            return VisualizationRecommendation(
                type=VisualizationType.CARD, reason="Single metric detected"
            )

        if row_count > self.large_result_threshold:
            return VisualizationRecommendation(
                type=VisualizationType.TABLE,
                reason=f"Large result list ({row_count} rows)",
            )

        if data_shape == DataShape.TIME_SERIES:
            return VisualizationRecommendation(
                type=VisualizationType.LINE_CHART, reason="Time-series data detected"
            )

        if data_shape == DataShape.CATEGORICAL:
            if (
                AnalyticsIntent.DISTRIBUTION in intents
                and 0 < category_count <= self.max_pie_categories
            ):
                return VisualizationRecommendation(
                    type=VisualizationType.PIE_CHART,
                    reason="Composition across a small number of categories",
                )
            return VisualizationRecommendation(
                type=VisualizationType.BAR_CHART, reason="Category comparison detected"
            )

        if data_shape == DataShape.SINGLE_ROW:
            return VisualizationRecommendation(
                type=VisualizationType.CARD, reason="Single record summary"
            )

        return VisualizationRecommendation(
            type=VisualizationType.TABLE, reason="General tabular result"
        )
