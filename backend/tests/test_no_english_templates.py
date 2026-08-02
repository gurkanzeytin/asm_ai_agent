"""All deterministic user-facing templates must be Turkish — no English
fallback strings in report titles, rule wordings, or observation templates.
"""

import re

from app.analytics.models import AnalyticsIntent
from app.insights import templates as insight_templates
from app.intelligence import templates as intelligence_templates
from app.reporting import presentation
from app.semantics import catalog

# Curated common English function/report words. Deliberately excludes ambiguous
# tokens (e.g. "trend" as a Turkish loanword-adjacent term) that could produce
# false positives against legitimate Turkish sentences.
_ENGLISH_WORD_PATTERN = re.compile(
    r"\b(the|is|are|and|of|overview|report|analysis|category|highest|volume|"
    r"growth|declining|values|detected|dominates|significant|stable)\b",
    re.IGNORECASE,
)


def _all_strings(*sources: dict[str, str]) -> list[str]:
    strings: list[str] = []
    for source in sources:
        strings.extend(source.values())
    return strings


def test_insight_titles_are_turkish():
    for title in insight_templates._TITLES.values():
        assert not _ENGLISH_WORD_PATTERN.search(title), title


def test_intelligence_rule_wordings_are_turkish():
    for wording in intelligence_templates.RULE_WORDINGS.values():
        assert not _ENGLISH_WORD_PATTERN.search(wording), wording


def test_intelligence_metric_wordings_are_turkish():
    for wording in (
        intelligence_templates.TOP_CATEGORY_WORDING,
        intelligence_templates.LARGEST_CHANGE_WORDING,
        intelligence_templates.SIGNIFICANT_SPREAD_WORDING,
    ):
        assert not _ENGLISH_WORD_PATTERN.search(wording), wording


def test_forbidden_wording_patterns_are_turkish():
    for pattern in intelligence_templates.FORBIDDEN_WORDING_PATTERNS:
        assert not _ENGLISH_WORD_PATTERN.search(pattern), pattern


def test_single_category_limitation_is_turkish():
    assert not _ENGLISH_WORD_PATTERN.search(insight_templates.SINGLE_CATEGORY_LIMITATION)


def test_every_planner_analysis_type_has_a_turkish_label():
    """`get_analysis_type_label` falls back to English Title Case for any
    analysis type missing from the map ('duration_analysis' -> 'Duration
    Analysis'). Both vocabularies that reach it must therefore be complete:
    QueryPlan.analysis_type (pattern ids + metric analysis types) and
    AnalyticsIntent.
    """
    planner_types = {pattern.id for pattern in catalog.load_pattern_catalog().patterns} | {
        metric.analysis_type for metric in catalog.load_metric_catalog().metrics
    }
    intent_types = {intent.value for intent in AnalyticsIntent}

    missing = sorted(
        value
        for value in planner_types | intent_types
        if value not in presentation.ANALYSIS_TYPE_LABELS_TR
    )

    assert not missing, f"Türkçe etiketi olmayan analiz tipleri: {missing}"


def test_analysis_type_labels_are_turkish():
    for label in presentation.ANALYSIS_TYPE_LABELS_TR.values():
        assert not _ENGLISH_WORD_PATTERN.search(label), label
