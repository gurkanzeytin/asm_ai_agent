"""Deterministic analytical-intent detection from natural-language questions.

Pattern-based (no LLM, no prompt engineering). Matching is Turkish
diacritic-insensitive and tolerant of agglutinative suffixes: every pattern
token matches as a word prefix (``dagilim`` also matches ``dağılımı``).
"""

import logging
import re

from app.analytics.models import AnalyticsIntent

logger = logging.getLogger(__name__)

_TURKISH_FOLD_TABLE = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ş": "s",
        "Ş": "s",
        "ç": "c",
        "Ç": "c",
        "ö": "o",
        "Ö": "o",
        "ü": "u",
        "Ü": "u",
    }
)

# Patterns are matched against the folded lowercase question. Each entry is a
# regex fragment; plain words match as word prefixes. Add new expressions here —
# no other code changes are needed.
_INTENT_PATTERNS: dict[AnalyticsIntent, list[str]] = {
    AnalyticsIntent.TREND: ["analiz", "trend", "egilim", "seyir", "seyri", "gidisat"],
    AnalyticsIntent.GROWTH_RATE: [
        "artis orani",
        "buyume",
        "buyuyen",
        "artis",
        "azalis",
        "dusus orani",
    ],
    AnalyticsIntent.PERCENTAGE_CHANGE: ["yuzde", "yuzdelik", "degisim orani", "degisim"],
    AnalyticsIntent.COMPARISON: [
        "karsilastir",
        "kiyasla",
        "hangisi daha",
        "hangi .{0,30}? daha",
        "daha yogun",
        "daha fazla",
        "daha az",
        "daha cok",
        "gore",
        "fark",
    ],
    AnalyticsIntent.RANKING: [
        "en fazla",
        "en cok",
        "en az",
        "en yuksek",
        "en dusuk",
        "en hizli",
        "en yavas",
        "en yogun",
        "en bos",
        r"ilk \d+",
        "sirala",
        "siralama",
    ],
    AnalyticsIntent.DISTRIBUTION: [
        "dagilim",
        "kompozisyon",
        "paylasim",
        "paylari",
        "yuzdeleri",
        "oranlari",
    ],
    AnalyticsIntent.AVERAGE: ["ortalama"],
    AnalyticsIntent.MEDIAN: ["medyan", "ortanca"],
    AnalyticsIntent.MINIMUM: ["minimum", "en dusuk", "en az"],
    AnalyticsIntent.MAXIMUM: ["maksimum", "en yuksek", "en fazla", "en cok"],
    AnalyticsIntent.TIME_SERIES: [
        "gunluk",
        "haftalik",
        "aylik",
        "yillik",
        "saatlik",
        "zaman",
        r"son \d+ (?:gun|hafta|ay|yil)",
    ],
    AnalyticsIntent.CORRELATION: ["korelasyon", "iliski"],
    AnalyticsIntent.FORECAST: ["tahmin", "ongoru", "gelecek"],
}

# When several intents match, the first one in this order names the analysis.
_PRIMARY_PRECEDENCE: list[AnalyticsIntent] = [
    AnalyticsIntent.TREND,
    AnalyticsIntent.GROWTH_RATE,
    AnalyticsIntent.COMPARISON,
    AnalyticsIntent.DISTRIBUTION,
    AnalyticsIntent.RANKING,
    AnalyticsIntent.PERCENTAGE_CHANGE,
    AnalyticsIntent.MEDIAN,
    AnalyticsIntent.AVERAGE,
    AnalyticsIntent.MINIMUM,
    AnalyticsIntent.MAXIMUM,
    AnalyticsIntent.TIME_SERIES,
    AnalyticsIntent.CORRELATION,
    AnalyticsIntent.FORECAST,
]


class AnalyticsIntentDetector:
    """Rule-based detector mapping Turkish analytical wording to AnalyticsIntent values."""

    def detect(self, question: str) -> list[AnalyticsIntent]:
        """Returns all analytical intents matched in the question (may be empty)."""
        folded = self._fold(question)
        detected: list[AnalyticsIntent] = []
        for intent, patterns in _INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(r"\b" + pattern + r"\w*", folded):
                    detected.append(intent)
                    break
        return detected

    def primary_intent(self, intents: list[AnalyticsIntent]) -> AnalyticsIntent:
        """Selects the intent that names the overall analysis."""
        for intent in _PRIMARY_PRECEDENCE:
            if intent in intents:
                return intent
        return AnalyticsIntent.GENERAL

    def _fold(self, text: str) -> str:
        # Map İ before lower(): Python lowercases it to "i" + U+0307 combining dot.
        lowered = text.replace("İ", "i").lower().replace("̇", "")
        return lowered.translate(_TURKISH_FOLD_TABLE)
