"""Deterministic business-rule evaluation over analytics results.

Runs BEFORE any LLM involvement. Rules and confidence are pure functions of the
AnalyticsResult — no LLM, no I/O, no randomness.
"""

import logging

from app.analytics.models import AnalyticsResult, DataShape
from app.insights.models import InsightConfidence, InsightRule

logger = logging.getLogger(__name__)

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

# analytics.trend_metrics.trend_consistency -> InsightRule, computed over
# comparable (complete) periods only. Replaces the old independent
# growth_rate/trend_direction rule blocks, which could contradict each other
# (e.g. DECLINING + POSITIVE_TREND firing together on the same series).
_CONSISTENCY_RULES: dict[str, InsightRule] = {
    "insufficient_data": InsightRule.INSUFFICIENT_COMPLETE_PERIODS,
    "consistent_upward": InsightRule.CONSISTENT_UPWARD_TREND,
    "consistent_downward": InsightRule.CONSISTENT_DOWNWARD_TREND,
    # AI-INTELLIGENCE-018: "mixed" renamed "mixed_or_fluctuating" — consistency
    # is now derived from adjacent-pair monotonicity (app.analytics.trend_analysis),
    # not endpoint/slope agreement, so this branch now specifically means
    # "the series fluctuated" rather than merely "the two summaries disagreed".
    "mixed_or_fluctuating": InsightRule.MIXED_TREND_SIGNAL,
    "flat": InsightRule.FLAT_TREND,
}


class InsightRulesEngine:
    """Maps deterministic analytics metrics to business rules and confidence."""

    def evaluate(self, analytics: AnalyticsResult) -> list[InsightRule]:
        metrics = analytics.metrics
        rules: list[InsightRule] = []

        has_direct_aggregate_kpi = analytics.aggregate_result and bool(
            analytics.displayable_kpis
        )
        if (
            analytics.row_count == 0
            or not metrics
            or (not has_direct_aggregate_kpi and metrics.get("count", 0) == 0)
        ):
            return [InsightRule.INSUFFICIENT_EVIDENCE]

        if analytics.data_shape == DataShape.TIME_SERIES and analytics.trend_metrics:
            trend_metrics = analytics.trend_metrics
            rule = _CONSISTENCY_RULES.get(trend_metrics.trend_consistency)
            if rule:
                rules.append(rule)
            if trend_metrics.comparison_excluded_partial_period:
                rules.append(InsightRule.PARTIAL_PERIOD_EXCLUDED)

        if (
            analytics.data_shape == DataShape.CATEGORICAL
            and analytics.comparison_category_count == 1
        ):
            rules.append(InsightRule.SINGLE_CATEGORY_COMPARISON)

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

        if analytics.aggregate_result and analytics.displayable_kpis:
            expected = tuple(item.key for item in analytics.displayable_kpis)
        else:
            expected = _EXPECTED_METRICS.get(analytics.data_shape, ("count",))
        missing = [name for name in expected if analytics.metrics.get(name) is None]
        if missing:
            logger.debug("Insight confidence downgraded to MEDIUM; missing metrics: %s", missing)
            return InsightConfidence.MEDIUM
        if not rules:
            return InsightConfidence.MEDIUM

        # A disagreeing endpoint-vs-slope signal, or too few complete periods
        # to verify a trend at all, is genuine but weaker evidence — real
        # data, just not a single clean conclusion. Never LOW: the query
        # executed and produced real numbers, just not a confident trend.
        weaker_trend_evidence = (
            InsightRule.MIXED_TREND_SIGNAL in rules
            or InsightRule.INSUFFICIENT_COMPLETE_PERIODS in rules
        )
        if weaker_trend_evidence:
            return InsightConfidence.MEDIUM

        return InsightConfidence.HIGH
