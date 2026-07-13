"""Deterministic business-rule evaluation over analytics results.

Runs BEFORE any LLM involvement. Rules and confidence are pure functions of the
AnalyticsResult — no LLM, no I/O, no randomness.
"""

import logging

from app.analytics.models import AnalyticsResult, DataShape
from app.insights.models import InsightConfidence, InsightRule

logger = logging.getLogger(__name__)

_HIGH_GROWTH_THRESHOLD = 15.0
_DOMINANT_SHARE_THRESHOLD = 50.0
_BALANCED_SPREAD_THRESHOLD = 10.0  # max-min share difference in percentage points
_OUTLIER_RATIO = 1.5  # top value vs average

# Metrics that must be present per data shape for HIGH confidence.
_EXPECTED_METRICS: dict[DataShape, tuple[str, ...]] = {
    DataShape.TIME_SERIES: ("total", "average", "growth_rate", "trend_direction"),
    DataShape.CATEGORICAL: ("total", "average", "top_category"),
    DataShape.SINGLE_VALUE: ("total",),
    DataShape.SINGLE_ROW: ("count",),
    DataShape.TABULAR: ("count",),
}


class InsightRulesEngine:
    """Maps deterministic analytics metrics to business rules and confidence."""

    def evaluate(self, analytics: AnalyticsResult) -> list[InsightRule]:
        metrics = analytics.metrics
        rules: list[InsightRule] = []

        if analytics.row_count == 0 or not metrics or metrics.get("count", 0) == 0:
            return [InsightRule.INSUFFICIENT_EVIDENCE]

        growth_rate = metrics.get("growth_rate")
        if isinstance(growth_rate, (int, float)):
            if growth_rate > _HIGH_GROWTH_THRESHOLD:
                rules.append(InsightRule.HIGH_GROWTH)
            elif growth_rate >= 0:
                rules.append(InsightRule.MODERATE_GROWTH)
            else:
                rules.append(InsightRule.DECLINING)

        trend = metrics.get("trend_direction")
        if trend == "upward":
            rules.append(InsightRule.POSITIVE_TREND)
        elif trend == "downward":
            rules.append(InsightRule.NEGATIVE_TREND)
        elif trend == "stable":
            rules.append(InsightRule.STABLE_TREND)

        distribution = metrics.get("distribution")
        if isinstance(distribution, dict) and len(distribution) >= 2:
            shares = list(distribution.values())
            max_share, min_share = max(shares), min(shares)
            if max_share > _DOMINANT_SHARE_THRESHOLD:
                rules.append(InsightRule.DOMINANT_CATEGORY)
            elif max_share - min_share <= _BALANCED_SPREAD_THRESHOLD:
                rules.append(InsightRule.BALANCED_DISTRIBUTION)

        if analytics.data_shape == DataShape.CATEGORICAL:
            maximum = metrics.get("maximum")
            average = metrics.get("average")
            if (
                isinstance(maximum, (int, float))
                and isinstance(average, (int, float))
                and average > 0
                and maximum > average * _OUTLIER_RATIO
            ):
                rules.append(InsightRule.OUTLIER_DETECTED)

        if analytics.data_shape == DataShape.SINGLE_VALUE:
            rules.append(InsightRule.SINGLE_METRIC)

        return rules

    def compute_confidence(
        self, analytics: AnalyticsResult, rules: list[InsightRule]
    ) -> InsightConfidence:
        """Deterministic confidence — the LLM never generates this value.

        HIGH:   analytics complete for its shape and at least one rule detected.
        MEDIUM: some expected metrics unavailable, or data present but no rule fired.
        LOW:    insufficient analytical evidence.
        """
        if InsightRule.INSUFFICIENT_EVIDENCE in rules:
            return InsightConfidence.LOW
        if analytics.row_count == 0 or not analytics.metrics:
            return InsightConfidence.LOW

        expected = _EXPECTED_METRICS.get(analytics.data_shape, ("count",))
        missing = [name for name in expected if analytics.metrics.get(name) is None]
        if missing:
            logger.debug("Insight confidence downgraded to MEDIUM; missing metrics: %s", missing)
            return InsightConfidence.MEDIUM
        if not rules:
            return InsightConfidence.MEDIUM
        return InsightConfidence.HIGH
