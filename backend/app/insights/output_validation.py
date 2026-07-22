"""Lightweight deterministic validation of LLM-produced insight narratives.

No second LLM call — every check here is a regex/substring match or a
deterministic-template substitution. On any doubt about language or content
safety, the whole narrative is replaced by the existing, always-correct
``templates.build_deterministic_narrative`` rather than attempting to patch
or machine-translate free text.
"""

import logging
import re

from pydantic import BaseModel, ConfigDict

from app.analytics.models import AnalyticsResult
from app.insights import templates
from app.insights.models import InsightNarrative, InsightRule
from app.insights.narrative_guard import repair_narrative

logger = logging.getLogger(__name__)

# Curated common English function/report words — a density-based heuristic,
# not true language detection. Deliberately conservative (no bare "trend" or
# other Turkish-adjacent loanwords) to avoid false positives on legitimate
# Turkish sentences that happen to include a borrowed term or a data label.
ENGLISH_WORD_PATTERN = re.compile(
    r"\b(the|is|are|and|of|overview|report|analysis|category|highest|volume|"
    r"growth|declining|values|detected|dominates|significant|stable)\b",
    re.IGNORECASE,
)

# Body text with at least this many distinct English-marker matches is
# treated as non-Turkish and replaced wholesale — a single incidental match
# (e.g. an echoed English column name) is not enough on its own.
_ENGLISH_BODY_MATCH_THRESHOLD = 2

# Turkish phrases asserting a cause as an established fact rather than a
# hypothesis — dropped (never rewritten/fabricated) wherever they appear in
# LLM-authored "considerations" (the "Olası Açıklamalar" section).
_CAUSAL_CERTAINTY_PATTERNS = (
    "kesin nedeni",
    "kanıtlanmıştır",
    "kesinlikle",
    "şüphesiz",
)

# AI-INTELLIGENCE-018 (item 9): unsupported HEDGED causal speculation — the
# view has no operational/process data (no logs, no staff records, no system
# events), so "there might be a data-collection problem" is never evidence-
# backed, even hedged with "olabilir". Dropped the same way as a certainty
# claim; never rewritten into a stronger claim.
_UNSUPPORTED_CAUSAL_SPECULATION_PATTERNS = (
    "veri toplama sorunu",
    "veri toplama problemi",
    "veri girişi sorunu",
    "veri girişiyle ilgili bir sorun",
    "kayıt sorunu olabilir",
    "sistemsel bir sorun olabilir",
)


class NarrativeValidationVerdict(BaseModel):
    """Safe, loggable diagnostic describing what the validator did — never
    carries the narrative text itself, only booleans/reasons."""

    model_config = ConfigDict(frozen=True)

    language_ok: bool = True
    title_replaced: bool = False
    narrative_replaced: bool = False
    missing_limitations_added: list[str] = []
    causal_certainty_dropped: int = 0
    continuous_growth_phrase_repaired: bool = False
    reason: str | None = None


def _looks_english(text: str) -> bool:
    return bool(ENGLISH_WORD_PATTERN.search(text or ""))


def _body_english_match_count(narrative: InsightNarrative) -> int:
    body = " ".join(
        [
            narrative.summary,
            *narrative.highlights,
            *narrative.observations,
            *narrative.considerations,
        ]
    )
    return len(ENGLISH_WORD_PATTERN.findall(body))


def validate_and_repair(
    narrative: InsightNarrative,
    analytics: AnalyticsResult,
    rules: list[InsightRule],
) -> tuple[InsightNarrative, NarrativeValidationVerdict]:
    """Repairs an LLM-produced narrative in place where safely possible,
    falling back to the deterministic narrative when it isn't."""
    # 1. Structurally empty output — no title/summary to work with at all.
    if not narrative.title or not narrative.summary:
        fallback = templates.build_deterministic_narrative(analytics, rules)
        return fallback, NarrativeValidationVerdict(
            language_ok=False,
            narrative_replaced=True,
            reason="empty_title_or_summary",
        )

    # 2. English body text — can't safely machine-translate free text, so the
    # whole narrative is replaced by the deterministic (always Turkish, always
    # spec-compliant per Phases 1-4) builder.
    if _body_english_match_count(narrative) >= _ENGLISH_BODY_MATCH_THRESHOLD:
        fallback = templates.build_deterministic_narrative(analytics, rules)
        return fallback, NarrativeValidationVerdict(
            language_ok=False,
            narrative_replaced=True,
            reason="llm_output_not_turkish",
        )

    title_replaced = False
    title = narrative.title
    if _looks_english(title):
        title = templates.build_title(analytics)
        title_replaced = True

    considerations = list(narrative.considerations)
    missing_limitations: list[str] = []

    if analytics.comparison_sufficient is False and analytics.comparison_limitation_reason:
        if not any(analytics.comparison_limitation_reason in text for text in considerations):
            considerations.append(analytics.comparison_limitation_reason)
            missing_limitations.append("comparison_limitation")

    trend_metrics = analytics.trend_metrics
    if trend_metrics is not None and trend_metrics.comparison_excluded_partial_period:
        excluded = ", ".join(trend_metrics.excluded_periods)
        sentence = (
            f"{excluded} dönemi henüz tamamlanmadığı için eğilim hesabında tam "
            "dönemlerle birlikte değerlendirilmemiştir."
        )
        if not any(excluded in text for text in considerations):
            considerations.append(sentence)
            missing_limitations.append("partial_period_excluded")

    causal_dropped = 0
    filtered_considerations = []
    for text in considerations:
        lowered = text.lower()
        if any(pattern in lowered for pattern in _CAUSAL_CERTAINTY_PATTERNS):
            causal_dropped += 1
            logger.warning("Dropped considerations entry with unsupported causal certainty.")
            continue
        if any(pattern in lowered for pattern in _UNSUPPORTED_CAUSAL_SPECULATION_PATTERNS):
            causal_dropped += 1
            logger.warning("Dropped considerations entry with unsupported causal speculation.")
            continue
        filtered_considerations.append(text)

    repaired = narrative.model_copy(
        update={"title": title, "considerations": filtered_considerations}
    )

    # AI-INTELLIGENCE-018 (item 8): never let an upward endpoint or positive
    # slope alone stand in for "continuous/uninterrupted growth" — repair or
    # drop the claim whenever the deterministic trend verdict says the series
    # actually fluctuated (monotonicity == "non_monotonic").
    before = repaired
    repaired = repair_narrative(repaired, trend_metrics)
    continuous_growth_repaired = repaired != before

    return repaired, NarrativeValidationVerdict(
        language_ok=True,
        title_replaced=title_replaced,
        narrative_replaced=False,
        missing_limitations_added=missing_limitations,
        causal_certainty_dropped=causal_dropped,
        continuous_growth_phrase_repaired=continuous_growth_repaired,
        reason=None,
    )
