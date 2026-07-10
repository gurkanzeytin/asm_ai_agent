import json
import logging
import re
import string
import unicodedata
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.application_models.query_analysis import DateRange, DetectedEntity, QueryAnalysis
from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_SYNONYMS_PATH = Path(__file__).resolve().parents[1] / "resources" / "domain_synonyms.json"

_MONTHS = {
    "ocak": 1,
    "subat": 2,
    "şubat": 2,
    "mart": 3,
    "nisan": 4,
    "mayis": 5,
    "mayıs": 5,
    "haziran": 6,
    "temmuz": 7,
    "agustos": 8,
    "ağustos": 8,
    "eylul": 9,
    "eylül": 9,
    "ekim": 10,
    "kasim": 11,
    "kasım": 11,
    "aralik": 12,
    "aralık": 12,
}


class QueryAnalyzer:
    """Deterministic natural-language normalizer for schema retrieval."""

    def __init__(self, synonyms_path: Path | None = None, today: date | None = None) -> None:
        self.synonyms_path = synonyms_path or _DEFAULT_SYNONYMS_PATH
        self.today = today
        self._rules: dict[str, Any] | None = None
        self._rules_mtime: float | None = None

    def analyze(self, query: str) -> QueryAnalysis:
        rules = self._load_rules()
        original_query = query
        normalized_query = self._normalize_query_text(query)
        rewritten_query, matched_synonyms = self._rewrite_query(normalized_query, rules)
        rewritten_query, fallback_synonyms = self._apply_domain_rewrite_fallbacks(rewritten_query)
        matched_synonyms.extend(fallback_synonyms)
        entities = self._detect_entities(rewritten_query, normalized_query, rules)
        detected_dates = self._detect_dates(normalized_query)
        confidence = self._confidence(entities, detected_dates, matched_synonyms)

        analysis = QueryAnalysis(
            original_query=original_query,
            normalized_query=rewritten_query,
            entities=entities,
            detected_dates=detected_dates,
            matched_synonyms=matched_synonyms,
            confidence=confidence,
        )
        self._log_analysis(analysis)
        return analysis

    def _load_rules(self) -> dict[str, Any]:
        mtime = self.synonyms_path.stat().st_mtime
        should_reload = (
            self._rules is None
            or self._rules_mtime is None
            or settings.DEBUG
            or mtime != self._rules_mtime
        )
        if should_reload:
            with open(self.synonyms_path, encoding="utf-8") as file:
                self._rules = json.load(file)
            self._rules_mtime = mtime
        return self._rules or {"entities": {}, "rewrites": []}

    def _normalize_query_text(self, query: str) -> str:
        lowered = query.lower().strip()
        punctuation = string.punctuation.replace("-", "")
        translator = str.maketrans({char: " " for char in punctuation})
        normalized = lowered.translate(translator)
        return re.sub(r"\s+", " ", normalized).strip()

    def _rewrite_query(self, query: str, rules: dict[str, Any]) -> tuple[str, list[str]]:
        rewritten = query
        matched: list[str] = []
        for rule in rules.get("rewrites", []):
            pattern = self._normalize_query_text(str(rule.get("pattern", "")))
            replacement = self._normalize_query_text(str(rule.get("replacement", "")))
            if not pattern or pattern not in rewritten:
                continue
            rewritten = re.sub(rf"\b{re.escape(pattern)}\b", replacement, rewritten)
            matched.append(str(rule.get("matched_synonym", f"{pattern} -> {replacement}")))
        return re.sub(r"\s+", " ", rewritten).strip(), matched

    def _apply_domain_rewrite_fallbacks(self, query: str) -> tuple[str, list[str]]:
        query_ascii = self._strip_diacritics(query)
        if "yogun" in query_ascii and "bolum" in query_ascii and "randevu" not in query_ascii:
            rewritten = re.sub(r"\byogun\b", "fazla randevusu olan", query_ascii)
            return re.sub(r"\s+", " ", rewritten).strip(), [
                "yogun bolum -> en fazla randevu"
            ]
        return query, []

    def _detect_entities(
        self,
        rewritten_query: str,
        original_normalized_query: str,
        rules: dict[str, Any],
    ) -> list[DetectedEntity]:
        entities: list[DetectedEntity] = []
        searchable = f"{original_normalized_query} {rewritten_query}"
        normalized_searchable = self._strip_diacritics(searchable)
        seen: set[tuple[str, str]] = set()

        for entity_type, spec in rules.get("entities", {}).items():
            canonical = str(spec.get("canonical", entity_type.lower()))
            for term in spec.get("terms", []):
                term_text = str(term)
                normalized_term = self._strip_diacritics(self._normalize_query_text(term_text))
                if not normalized_term:
                    continue
                if re.search(rf"\b{re.escape(normalized_term)}\w*\b", normalized_searchable):
                    key = (entity_type, canonical)
                    if key in seen:
                        continue
                    seen.add(key)
                    entities.append(
                        DetectedEntity(
                            entity_type=entity_type,
                            canonical=canonical,
                            text=term_text,
                            normalized_text=normalized_term,
                            confidence=1.0,
                        )
                    )
                    break
        return entities

    def _detect_dates(self, query: str) -> list[DateRange]:
        today = self.today or date.today()
        query_ascii = self._strip_diacritics(query)
        ranges: list[DateRange] = []

        exact_days = {
            "bugun": (today, today, "day"),
            "yarin": (today + timedelta(days=1), today + timedelta(days=1), "day"),
            "dun": (today - timedelta(days=1), today - timedelta(days=1), "day"),
        }
        for expression, (start, end, granularity) in exact_days.items():
            if re.search(rf"\b{expression}\b", query_ascii):
                ranges.append(self._date_range(expression, start, end, granularity))

        if "gecen hafta" in query_ascii:
            this_week_start = today - timedelta(days=today.weekday())
            start = this_week_start - timedelta(days=7)
            ranges.append(self._date_range("gecen hafta", start, start + timedelta(days=6), "week"))

        if "gecen ay" in query_ascii:
            year = today.year if today.month > 1 else today.year - 1
            month = today.month - 1 if today.month > 1 else 12
            ranges.append(self._month_range("gecen ay", year, month))

        if "bu yil" in query_ascii:
            ranges.append(self._date_range("bu yil", date(today.year, 1, 1), today, "year"))

        if "gecen yil" in query_ascii:
            year = today.year - 1
            ranges.append(
                self._date_range("gecen yil", date(year, 1, 1), date(year, 12, 31), "year")
            )

        for match in re.finditer(r"\bson\s+(\d+)\s+gun\b", query_ascii):
            days = int(match.group(1))
            start = today - timedelta(days=max(days - 1, 0))
            ranges.append(self._date_range(match.group(0), start, today, "day"))

        for month_name, month in _MONTHS.items():
            if re.search(rf"\b{self._strip_diacritics(month_name)}\s+ayinda\b", query_ascii):
                ranges.append(self._month_range(f"{month_name} ayinda", today.year, month))

        for match in re.finditer(r"\b(20\d{2}|19\d{2})\s+yilinda\b", query_ascii):
            year = int(match.group(1))
            ranges.append(
                self._date_range(match.group(0), date(year, 1, 1), date(year, 12, 31), "year")
            )

        return ranges

    def _date_range(
        self,
        expression: str,
        start_date: date,
        end_date: date,
        granularity: str,
    ) -> DateRange:
        return DateRange(
            expression=expression,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
        )

    def _month_range(self, expression: str, year: int, month: int) -> DateRange:
        last_day = monthrange(year, month)[1]
        return self._date_range(
            expression,
            date(year, month, 1),
            date(year, month, last_day),
            "month",
        )

    def _confidence(
        self,
        entities: list[DetectedEntity],
        detected_dates: list[DateRange],
        matched_synonyms: list[str],
    ) -> float:
        score = 0.45
        if entities:
            score += min(0.35, len(entities) * 0.12)
        if detected_dates:
            score += 0.1
        if matched_synonyms:
            score += min(0.1, len(matched_synonyms) * 0.05)
        return min(0.99, score)

    def _strip_diacritics(self, text: str) -> str:
        text = text.translate(
            str.maketrans(
                {
                    "ı": "i",
                    "İ": "I",
                    "ğ": "g",
                    "Ğ": "G",
                    "ş": "s",
                    "Ş": "S",
                    "ç": "c",
                    "Ç": "C",
                    "ö": "o",
                    "Ö": "O",
                    "ü": "u",
                    "Ü": "U",
                }
            )
        )
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(char for char in normalized if not unicodedata.combining(char))

    def _log_analysis(self, analysis: QueryAnalysis) -> None:
        logger.info(
            "\n================ QUERY ANALYSIS ================\n"
            f"Original Query\n{analysis.original_query}\n\n"
            f"Normalized Query\n{analysis.normalized_query}\n\n"
            "Detected Entities\n"
            f"{', '.join(entity.entity_type for entity in analysis.entities) or 'None'}\n\n"
            "Matched Synonyms\n"
            f"{', '.join(analysis.matched_synonyms) or 'None'}\n\n"
            "Date Expressions\n"
            f"{', '.join(self._date_expressions(analysis)) or 'None'}\n\n"
            f"Confidence\n{analysis.confidence:.2f}\n"
            "================================================",
            extra={
                "original_query": analysis.original_query,
                "normalized_query": analysis.normalized_query,
                "entities": [entity.entity_type for entity in analysis.entities],
                "matched_synonyms": analysis.matched_synonyms,
                "date_expressions": self._date_expressions(analysis),
                "confidence": analysis.confidence,
            },
        )

    def _date_expressions(self, analysis: QueryAnalysis) -> list[str]:
        return [date_range.expression for date_range in analysis.detected_dates]
