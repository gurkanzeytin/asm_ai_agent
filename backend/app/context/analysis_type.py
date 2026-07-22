"""Canonical conversational analysis-type mapping.

Root-cause fix: the context engine previously derived the persisted
``analysis_type`` purely from ``ContextExtractor``'s keyword scan of the raw
question text (see ``ContextExtractor._detect_analysis_type``). That
detector never sees the actual, deterministically computed result of the
workflow — so a question the pipeline correctly classified and executed as
TREND (``AnalyticsResult.analytics_type == "trend"``) could be persisted to
conversational memory as ``list`` merely because the wording lacked trend
cue words. This module defines the one canonical enum used for persistence
and a deterministic mapper from the *actual* post-execution analytics
result (and, for non-analytical terminal outcomes, the workflow outcome) —
never from the pre-execution keyword guess.
"""

from enum import StrEnum


class CanonicalAnalysisType(StrEnum):
    """The only vocabulary conversational memory persists as ``analysis_type``."""

    LIST = "list"
    FILTER = "filter"
    SUMMARY = "summary"
    DISTRIBUTION = "distribution"
    COMPARISON = "comparison"
    TREND = "trend"
    RANKING = "ranking"
    DATA_QUALITY = "data_quality"
    CLARIFICATION = "clarification"
    OUT_OF_SCOPE = "out_of_scope"


# AnalyticsResult.analytics_type -> CanonicalAnalysisType. Source values come
# from app.analytics.analytics_engine._analytics_type: either an
# AnalyticsIntent.value (trend, comparison, growth_rate, percentage_change,
# ranking, distribution, average, median, minimum, maximum, time_series,
# correlation, forecast) or one of its shape-fallback strings
# (summary, none, list).
_ANALYTICS_TYPE_MAP: dict[str, CanonicalAnalysisType] = {
    "trend": CanonicalAnalysisType.TREND,
    "growth_rate": CanonicalAnalysisType.TREND,
    "percentage_change": CanonicalAnalysisType.TREND,
    "time_series": CanonicalAnalysisType.TREND,
    "forecast": CanonicalAnalysisType.TREND,
    "comparison": CanonicalAnalysisType.COMPARISON,
    "ranking": CanonicalAnalysisType.RANKING,
    "distribution": CanonicalAnalysisType.DISTRIBUTION,
    "correlation": CanonicalAnalysisType.SUMMARY,
    "average": CanonicalAnalysisType.SUMMARY,
    "median": CanonicalAnalysisType.SUMMARY,
    "minimum": CanonicalAnalysisType.SUMMARY,
    "maximum": CanonicalAnalysisType.SUMMARY,
    "summary": CanonicalAnalysisType.SUMMARY,
    "none": CanonicalAnalysisType.SUMMARY,
    "list": CanonicalAnalysisType.LIST,
}

# AgentOutcome.value -> CanonicalAnalysisType, for terminal states that never
# reach the analytics engine at all (or superseded it, e.g. clarification).
_OUTCOME_TYPE_MAP: dict[str, CanonicalAnalysisType] = {
    "ASK_CLARIFICATION": CanonicalAnalysisType.CLARIFICATION,
    "OUT_OF_SCOPE": CanonicalAnalysisType.OUT_OF_SCOPE,
    "NO_RESULT_GUIDANCE": CanonicalAnalysisType.DATA_QUALITY,
}


def resolve_canonical_analysis_type(
    *,
    analytics_type: str | None = None,
    outcome: str | None = None,
) -> CanonicalAnalysisType | None:
    """Maps the workflow's final, deterministic result onto the canonical enum.

    ``outcome`` takes precedence for terminal states the analytics engine
    never ran for (clarification, out-of-scope, no-result-guidance) — those
    override any stale/absent ``analytics_type``. Otherwise the authoritative
    ``AnalyticsResult.analytics_type`` computed post-execution is mapped.
    Returns ``None`` when neither signal is available (nothing to persist).
    """
    if outcome and outcome in _OUTCOME_TYPE_MAP:
        return _OUTCOME_TYPE_MAP[outcome]
    if analytics_type:
        mapped = _ANALYTICS_TYPE_MAP.get(analytics_type)
        if mapped is not None:
            return mapped
    return None
