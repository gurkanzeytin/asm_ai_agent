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
from app.reporting.presentation import get_visualization_label

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
        metric_count: int = 1,
        requested_type: str | None = None,
    ) -> VisualizationRecommendation:
        recommendation = self._select(data_shape, intents, row_count, category_count, metric_count)
        # An EXPLICIT user chart request ("pasta grafik olarak göster") overrides
        # the shape-based default — but only when the data can actually be drawn
        # that way, so an impossible request (a pie of 40 categories, any chart
        # of an empty/single-value result) still degrades gracefully instead of
        # emitting a broken chart (2026-07-29, live UI findings).
        honored = self._honor_requested(
            requested_type, data_shape, row_count, category_count
        )
        if honored is not None and honored != recommendation.type:
            recommendation = recommendation.model_copy(
                update={
                    "type": honored,
                    "reason": f"Kullanıcının açıkça istediği grafik türü ({honored.value})",
                }
            )
        # Presentation metadata only: attach the Türkçe etiket, canonical
        # `type` is untouched and remains what all switching logic uses.
        return recommendation.model_copy(
            update={"type_label": get_visualization_label(recommendation.type.value)}
        )

    def _honor_requested(
        self,
        requested_type: str | None,
        data_shape: DataShape,
        row_count: int,
        category_count: int,
    ) -> VisualizationType | None:
        """Resolves an explicit chart request to a drawable type, or None when
        the data cannot support it (caller then keeps the shape-based default)."""
        if not requested_type:
            return None
        try:
            wanted = VisualizationType(requested_type)
        except ValueError:
            return None
        # Nothing categorical/temporal to plot — a chart would be empty or
        # meaningless; keep the card/table default.
        if data_shape in (DataShape.EMPTY, DataShape.SINGLE_VALUE, DataShape.SINGLE_ROW):
            return None
        if wanted == VisualizationType.PIE_CHART:
            # A pie needs a small, positive number of parts to stay legible.
            if not 0 < category_count <= self.max_pie_categories:
                return None
        return wanted

    def _select(
        self,
        data_shape: DataShape,
        intents: list[AnalyticsIntent],
        row_count: int,
        category_count: int = 0,
        metric_count: int = 1,
    ) -> VisualizationRecommendation:
        if data_shape == DataShape.EMPTY:
            return VisualizationRecommendation(
                type=VisualizationType.TABLE, reason="Empty result set"
            )

        if data_shape == DataShape.SINGLE_VALUE:
            return VisualizationRecommendation(
                type=VisualizationType.CARD, reason="Single metric detected"
            )

        # The large-result cutoff exists for CATEGORICAL data (a bar/pie chart
        # with 100+ slices is illegible) - it must not apply to TIME_SERIES,
        # where more points is the normal, desired case for a line chart (a
        # full year of daily counts is >30 rows and is exactly what a line
        # chart is for). Checked BEFORE the cutoff so dense time series never
        # get silently downgraded to a raw table.
        if data_shape == DataShape.TIME_SERIES:
            if metric_count >= 2:
                return VisualizationRecommendation(
                    type=VisualizationType.MULTI_SERIES_BAR_CHART,
                    reason=f"Time series with {metric_count} independent metrics",
                )
            return VisualizationRecommendation(
                type=VisualizationType.LINE_CHART, reason="Time-series data detected"
            )

        if row_count > self.large_result_threshold:
            return VisualizationRecommendation(
                type=VisualizationType.TABLE,
                reason=f"Large result list ({row_count} rows)",
            )

        if data_shape == DataShape.CATEGORICAL:
            if metric_count >= 2:
                return VisualizationRecommendation(
                    type=VisualizationType.GROUPED_BAR_CHART,
                    reason=f"Category comparison across {metric_count} independent metrics "
                    "(mixed units — never plotted on one shared scale)",
                )
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
