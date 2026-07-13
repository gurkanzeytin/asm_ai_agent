"""Deterministic narrative templates for the Insight Engine.

Used as the guaranteed-grounded fallback when the LLM is unavailable, fails,
or when evidence is insufficient. Every sentence is assembled exclusively from
values already present in the analytics object — nothing is invented.
"""

from app.analytics.models import AnalyticsResult
from app.insights.models import InsightNarrative, InsightRule

INSUFFICIENT_EVIDENCE_SUMMARY = "Insufficient analytical evidence."

_TITLES: dict[str, str] = {
    "trend": "Trend Analysis",
    "growth_rate": "Growth Analysis",
    "comparison": "Comparison Analysis",
    "ranking": "Ranking Analysis",
    "distribution": "Distribution Analysis",
    "average": "Average Analysis",
    "median": "Median Analysis",
    "minimum": "Minimum Analysis",
    "maximum": "Maximum Analysis",
    "time_series": "Time Series Analysis",
    "percentage_change": "Change Analysis",
    "summary": "Result Summary",
    "none": "Analysis Result",
    "list": "Result Overview",
}

_TREND_LABELS = {"upward": "an upward", "downward": "a downward", "stable": "a stable"}


def build_title(analytics: AnalyticsResult) -> str:
    return _TITLES.get(analytics.analytics_type, "Analysis Result")


def build_insufficient_evidence_narrative(analytics: AnalyticsResult) -> InsightNarrative:
    return InsightNarrative(
        title=build_title(analytics),
        summary=INSUFFICIENT_EVIDENCE_SUMMARY,
        highlights=[],
        observations=["The result set does not contain enough data to derive insights."],
        considerations=[],
    )


def build_deterministic_narrative(
    analytics: AnalyticsResult, rules: list[InsightRule]
) -> InsightNarrative:
    """Template-based narrative built strictly from computed metrics."""
    if InsightRule.INSUFFICIENT_EVIDENCE in rules:
        return build_insufficient_evidence_narrative(analytics)

    metrics = analytics.metrics
    highlights: list[str] = []
    observations: list[str] = []

    growth_rate = metrics.get("growth_rate")
    if isinstance(growth_rate, (int, float)):
        direction = "increased" if growth_rate >= 0 else "decreased"
        highlights.append(f"Values {direction} by {abs(growth_rate)}% over the period.")

    trend = metrics.get("trend_direction")
    if trend in _TREND_LABELS:
        highlights.append(f"The data shows {_TREND_LABELS[trend]} trend.")

    top_category = metrics.get("top_category")
    if top_category:
        highlights.append(f"'{top_category}' has the highest value.")

    largest_change = metrics.get("largest_change")
    if largest_change:
        highlights.append(f"The largest change occurred in {largest_change}.")

    total = metrics.get("total")
    if total is not None:
        observations.append(f"Total across the result set: {total}.")
    average = metrics.get("average")
    if average is not None:
        observations.append(f"Average value: {average}.")
    highest = metrics.get("highest_value")
    lowest = metrics.get("lowest_value")
    if highest is not None and lowest is not None:
        observations.append(f"Values range from {lowest} to {highest}.")

    if InsightRule.DOMINANT_CATEGORY in rules and top_category:
        observations.append(f"'{top_category}' accounts for more than half of the total.")
    if InsightRule.BALANCED_DISTRIBUTION in rules:
        observations.append("Values are distributed almost evenly across categories.")
    if InsightRule.OUTLIER_DETECTED in rules and top_category:
        observations.append(f"'{top_category}' is significantly above the average.")

    summary = highlights[0] if highlights else (
        observations[0] if observations else "Metrics were computed for the result set."
    )

    return InsightNarrative(
        title=build_title(analytics),
        summary=summary,
        highlights=highlights,
        observations=observations,
        considerations=[],
    )
