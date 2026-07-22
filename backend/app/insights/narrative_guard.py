"""Post-generation narrative validation (AI-INTELLIGENCE-018, item 8).

Rejects/repairs continuous-growth phrasing ("sürekli arttı", "tutarlı
yükseliş", ...) whenever the underlying trend is NOT actually monotonic —
grounds LLM/template narrative claims in the deterministic
`TrendMetrics.monotonicity` verdict rather than trusting an upward endpoint
or positive slope alone to imply continuous/uninterrupted growth.
"""

import re

from app.analytics.trend_analysis import TrendMetrics
from app.insights.models import InsightNarrative

# Turkish variants of "continuous/uninterrupted growth" claims — never valid
# when the series fluctuated (monotonicity == "non_monotonic"). Symmetric
# decline variants included since the same overclaim risk applies downward.
_FORBIDDEN_CONTINUOUS_GROWTH_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"sürekli\s+(?:art\w*|yüksel\w*|düş\w*|azal\w*)",
        r"kesintisiz\s+(?:art\w*|yüksel\w*|düş\w*|azal\w*)",
        r"her\s+ay\s+(?:art\w*|yüksel\w*|düş\w*|azal\w*)",
        r"istikrarlı\s+biçimde\s+(?:art\w*|yüksel\w*|düş\w*|azal\w*)",
        r"tutarlı\s+(?:bir\s+)?(?:yükseli[şs]|düşü[şs])",
    )
)

_ENDPOINT_ADJECTIVE_TR = {"upward": "yukarı", "downward": "aşağı", "flat": "yatay"}
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


def contains_forbidden_continuous_growth_phrase(text: str) -> bool:
    """True when `text` claims continuous/uninterrupted growth or decline."""
    return bool(text) and any(
        pattern.search(text) for pattern in _FORBIDDEN_CONTINUOUS_GROWTH_PATTERNS
    )


def _safe_fallback_sentence(trend_metrics: TrendMetrics) -> str:
    adjective = _ENDPOINT_ADJECTIVE_TR.get(trend_metrics.endpoint_direction, "belirsiz")
    return f"Dalgalanmalara rağmen dönem başından dönem sonuna genel yön {adjective}dır."


def repair_text(text: str, trend_metrics: TrendMetrics) -> str:
    """Replaces any forbidden continuous-growth sentence in `text` with the
    grounded fallback statement; drops duplicate forbidden sentences instead
    of repeating the fallback. Non-forbidden sentences pass through unchanged."""
    if not text or not contains_forbidden_continuous_growth_phrase(text):
        return text
    fallback = _safe_fallback_sentence(trend_metrics)
    sentences = _SENTENCE_SPLIT_PATTERN.split(text)
    repaired: list[str] = []
    fallback_inserted = False
    for sentence in sentences:
        if contains_forbidden_continuous_growth_phrase(sentence):
            if not fallback_inserted:
                repaired.append(fallback)
                fallback_inserted = True
            continue
        repaired.append(sentence)
    return " ".join(part for part in repaired if part).strip()


def repair_narrative(
    narrative: InsightNarrative, trend_metrics: TrendMetrics | None
) -> InsightNarrative:
    """Repairs every text field of `narrative` when the trend is non-monotonic.

    A no-op (returns `narrative` unchanged) whenever there is no trend context
    or the trend genuinely IS monotonic — this guard only ever REMOVES an
    unsupported claim, never invents language for a legitimately consistent
    trend.
    """
    if trend_metrics is None or trend_metrics.monotonicity != "non_monotonic":
        return narrative
    return narrative.model_copy(
        update={
            "summary": repair_text(narrative.summary, trend_metrics),
            "highlights": [repair_text(item, trend_metrics) for item in narrative.highlights],
            "observations": [
                repair_text(item, trend_metrics) for item in narrative.observations
            ],
            "considerations": [
                repair_text(item, trend_metrics) for item in narrative.considerations
            ],
        }
    )
