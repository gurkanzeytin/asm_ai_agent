"""Deterministic observation rules — analytics/insight metadata in, observations out.

No LLM, no SQL, no analytics calculations: this module only transforms already
computed facts into neutral observation statements with their grounding evidence.
"""

from typing import Any

from app.analytics.models import AnalyticsResult
from app.insights.models import InsightRule
from app.intelligence import templates
from app.intelligence.models import Observation, ObservationCategory

_RULE_CATEGORIES: dict[str, ObservationCategory] = {
    "HIGH_GROWTH": ObservationCategory.GROWTH,
    "MODERATE_GROWTH": ObservationCategory.GROWTH,
    "DECLINING": ObservationCategory.GROWTH,
    "POSITIVE_TREND": ObservationCategory.TREND,
    "NEGATIVE_TREND": ObservationCategory.TREND,
    "STABLE_TREND": ObservationCategory.TREND,
    "DOMINANT_CATEGORY": ObservationCategory.DISTRIBUTION,
    "BALANCED_DISTRIBUTION": ObservationCategory.DISTRIBUTION,
    "OUTLIER_DETECTED": ObservationCategory.RANKING,
    "SINGLE_METRIC": ObservationCategory.VOLUME,
    "INSUFFICIENT_EVIDENCE": ObservationCategory.DATA_QUALITY,
}

# A max/min ratio beyond this marks the spread between categories as significant.
_SIGNIFICANT_SPREAD_RATIO = 2.0


def build_observations(
    analytics: AnalyticsResult, rules: list[InsightRule]
) -> list[Observation]:
    """Derives deterministic observations from insight rules and analytics metrics."""
    metrics = analytics.metrics
    observations: list[Observation] = []
    seen_texts: set[str] = set()

    def add(
        rule: str,
        category: ObservationCategory,
        wording: str,
        evidence_keys: tuple[str, ...],
    ) -> None:
        evidence = {key: metrics.get(key) for key in evidence_keys if metrics.get(key) is not None}
        try:
            text = wording.format(**{key: metrics.get(key) for key in evidence_keys})
        except (KeyError, IndexError):
            return
        if "None" in text or text in seen_texts:
            return
        seen_texts.add(text)
        observations.append(
            Observation(rule=rule, category=category, text=text, evidence=evidence)
        )

    # 1. Rule-driven observations.
    for rule in rules:
        wording = templates.RULE_WORDINGS.get(rule.value)
        if not wording:
            continue
        category = _RULE_CATEGORIES.get(rule.value, ObservationCategory.VOLUME)
        add(rule.value, category, wording, _placeholders(wording))

    if InsightRule.INSUFFICIENT_EVIDENCE in rules:
        return observations

    # 2. Metric-driven observations (independent of rules).
    if metrics.get("top_category") is not None:
        add(
            "TOP_CATEGORY",
            ObservationCategory.RANKING,
            templates.TOP_CATEGORY_WORDING,
            ("top_category",),
        )
    if metrics.get("largest_change") is not None:
        add(
            "LARGEST_CHANGE",
            ObservationCategory.CHANGE,
            templates.LARGEST_CHANGE_WORDING,
            ("largest_change",),
        )
    if _has_significant_spread(metrics):
        add(
            "SIGNIFICANT_SPREAD",
            ObservationCategory.DISTRIBUTION,
            templates.SIGNIFICANT_SPREAD_WORDING,
            ("highest_value", "lowest_value"),
        )

    return observations


def _has_significant_spread(metrics: dict[str, Any]) -> bool:
    highest = metrics.get("highest_value")
    lowest = metrics.get("lowest_value")
    if not isinstance(highest, (int, float)) or not isinstance(lowest, (int, float)):
        return False
    if lowest <= 0 or highest == lowest:
        return False
    return highest / lowest >= _SIGNIFICANT_SPREAD_RATIO


def _placeholders(wording: str) -> tuple[str, ...]:
    """Extracts {placeholder} names from a template wording."""
    import string

    return tuple(
        field_name
        for _, field_name, _, _ in string.Formatter().parse(wording)
        if field_name
    )
