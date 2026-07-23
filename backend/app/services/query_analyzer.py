import json
import logging
import re
import string
import unicodedata
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.application_models.query_analysis import (
    AmbiguityResult,
    DateRange,
    DetectedEntity,
    QueryAnalysis,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_SYNONYMS_PATH = Path(__file__).resolve().parents[1] / "resources" / "domain_synonyms.json"

_BACK_VOWELS = set("aıou")
_FRONT_VOWELS = set("eiöü")
_VOWELS = _BACK_VOWELS | _FRONT_VOWELS

# One-to-one Turkish diacritic fold. Length-preserving so match positions on the
# folded text map directly back onto the original text during rewrites.
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
_TURKISH_FOLD_TABLE.update(
    {
        ord("\u0131"): "i",
        ord("\u0130"): "i",
        ord("\u011f"): "g",
        ord("\u011e"): "g",
        ord("\u015f"): "s",
        ord("\u015e"): "s",
        ord("\u00e7"): "c",
        ord("\u00c7"): "c",
        ord("\u00f6"): "o",
        ord("\u00d6"): "o",
        ord("\u00fc"): "u",
        ord("\u00dc"): "u",
    }
)

# Spelled-out Turkish counts (folded: ü->u, ç->c...), used alongside digits so
# "son üç ay" is detected exactly like "son 3 ay" — previously only \d+ was
# recognized, so a spelled-number relative period was silently invisible to
# date detection (detected_dates stayed empty for it).
_NUMBER_WORDS: dict[str, int] = {
    "bir": 1,
    "iki": 2,
    "uc": 3,
    "dort": 4,
    "bes": 5,
    "alti": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
}
_NUMBER_TOKEN = r"(\d+|" + "|".join(_NUMBER_WORDS) + r")"

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


_FORMAT_ONLY_SQL_MARKER = re.compile(r"\b(sql|sorgu\w*)\b")
_FORMAT_ONLY_OUTPUT_MARKER = re.compile(
    r"\b(tablo\w*|veri\w*|sonuc\w*|calistir\w*|getir\w*|liste\w*)\b"
)
_DOMAIN_SUBJECT_MARKER = re.compile(
    r"\b("
    r"randevu\w*|hasta\w*|doktor\w*|hekim\w*|kaynak\w*|"
    r"sube\w*|hastane\w*|lokasyon\w*|bolum\w*|brans\w*|klinik\w*|"
    r"kategori\w*|hizmet\w*|cinsiyet\w*|uyruk\w*|yas\w*|"
    r"durum\w*|bekleyen\w*|beklemede|gelmeyen\w*|gelmedi|"
    r"gerceklesen\w*|giris\w*|islem\w*|protokol\w*|"
    r"olusturulan\w*|olusturan\w*|kaydedilen\w*|sure\w*|"
    r"bugun\w*|dun\w*|yarin\w*|hafta\w*|ay\w*|yil\w*|tarih\w*"
    r")\b"
)


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
        normalized_input = self._normalize_query_text(query)

        # Structured signals are detected on the raw normalized text so that
        # conversational rewrites (e.g. "görebilir miyim" -> "göster") cannot
        # hide the user's original wording from detection.
        detected_operations = self._detect_operations(normalized_input, rules)
        detected_limit, detected_order = self._detect_limit_and_order(normalized_input)
        ambiguity = self._match_ambiguity(normalized_input, rules)

        rewritten_query, expanded_query, matched_synonyms = self._rewrite_stages(
            normalized_input, rules
        )
        entities = self._detect_entities(expanded_query, normalized_input, rules)
        detected_dates = self._detect_dates(normalized_input)
        final_query = self._resolve_dates(expanded_query, detected_dates)
        confidence = self._confidence(
            entities, detected_dates, matched_synonyms, detected_operations
        )

        analysis = QueryAnalysis(
            original_query=original_query,
            normalized_query=expanded_query,
            rewritten_query=rewritten_query,
            expanded_query=expanded_query,
            final_query=final_query,
            entities=entities,
            detected_dates=detected_dates,
            matched_synonyms=matched_synonyms,
            detected_operations=detected_operations,
            detected_limit=detected_limit,
            detected_order=detected_order,
            is_ambiguous=ambiguity is not None,
            ambiguity=ambiguity,
            confidence=confidence,
        )
        self._log_analysis(analysis)
        return analysis

    def detect_ambiguity(self, query: str) -> AmbiguityResult | None:
        """Checks whether a query is ambiguous or unanswerable with the available columns.

        Ambiguous ranking phrases ('en başarılı') and questions requiring data the
        view does not contain (diagnoses, payments, ...) both divert to the existing
        clarification flow instead of generating SQL over invented columns.
        """
        rules = self._load_rules()
        ambiguity = self._match_ambiguity(self._normalize_query_text(query), rules)
        if ambiguity is not None:
            return ambiguity

        from app.semantics import catalog

        folded = self._fold(self._normalize_query_text(query))
        if self._is_format_only_database_request(folded):
            return AmbiguityResult(
                matched_phrase="format_only_database_request",
                question="Hangi verinin sorgusunu olusturmami veya calistirmami istiyorsunuz?",
                options=[
                    "Bugun olusturulan son 20 randevuyu getir",
                    "Subelere gore randevu sayisini goster",
                    "Cinsiyete gore randevu dagilimini goster",
                ],
            )
        answerable, reason, alternative = catalog.check_answerability(folded)
        if not answerable:
            return AmbiguityResult(
                matched_phrase="unanswerable_concept",
                question=f"{reason} {alternative}",
                options=[alternative or "Farklı bir analiz", "Sorumu değiştireceğim"],
            )
        return None

    @staticmethod
    def _is_format_only_database_request(folded_query: str) -> bool:
        """True when the user asks for SQL/table output but omits the data subject."""
        return bool(
            _FORMAT_ONLY_SQL_MARKER.search(folded_query)
            and _FORMAT_ONLY_OUTPUT_MARKER.search(folded_query)
            and not _DOMAIN_SUBJECT_MARKER.search(folded_query)
        )

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
        # Turkish dotted capital İ lowercases to "i" + U+0307 combining dot in
        # Python; map it up front so word-boundary matching works on "İlk", "İç"...
        lowered = query.replace("İ", "i").lower().replace("̇", "").strip()
        lowered = lowered.replace("\u0307", "")
        punctuation = string.punctuation.replace("-", "")
        translator = str.maketrans({char: " " for char in punctuation})
        normalized = lowered.translate(translator)
        return re.sub(r"\s+", " ", normalized).strip()

    def _rewrite_stages(self, query: str, rules: dict[str, Any]) -> tuple[str, str, list[str]]:
        """Applies configured rewrite groups in order and returns staged outputs.

        Groups run in configuration order. The ``expansion`` group runs last and
        its output is tracked separately so logging can distinguish the rewrite
        stage from the query-expansion stage.
        """
        groups = self._rewrite_rule_groups(rules)
        matched: list[str] = []

        rewritten = query
        for name, group_rules in groups:
            if name == "expansion":
                continue
            rewritten, group_matched = self._apply_rewrite_rules(rewritten, group_rules)
            matched.extend(group_matched)

        expanded = rewritten
        for name, group_rules in groups:
            if name != "expansion":
                continue
            expanded, group_matched = self._apply_rewrite_rules(expanded, group_rules)
            matched.extend(group_matched)

        return rewritten, expanded, matched

    def _rewrite_rule_groups(self, rules: dict[str, Any]) -> list[tuple[str, list[dict]]]:
        """Collects rewrite rules from the flat legacy list and the grouped config."""
        groups: list[tuple[str, list[dict]]] = []
        legacy = rules.get("rewrites", [])
        if legacy:
            groups.append(("legacy", legacy))
        for name, group_rules in rules.get("rewrite_groups", {}).items():
            groups.append((str(name), list(group_rules)))
        return groups

    def _apply_rewrite_rules(self, query: str, rewrite_rules: list[dict]) -> tuple[str, list[str]]:
        rewritten = query
        matched: list[str] = []
        for rule in rewrite_rules:
            pattern = self._normalize_query_text(str(rule.get("pattern", "")))
            replacement = self._normalize_query_text(str(rule.get("replacement", "")))
            if not pattern:
                continue
            regex = self._compile_rewrite_pattern(pattern, rule)
            rewritten, rule_matched = self._replace_fold_insensitive(
                rewritten,
                regex,
                replacement,
                keep_suffix=bool(rule.get("match_suffix")),
            )
            if rule_matched:
                matched.append(str(rule.get("matched_synonym", f"{pattern} -> {replacement}")))
        return re.sub(r"\s+", " ", rewritten).strip(), matched

    def _compile_rewrite_pattern(self, pattern: str, rule: dict[str, Any]) -> str:
        body = r"\b" + re.escape(self._fold(pattern))
        if rule.get("match_suffix"):
            body += r"(\w*)"
        else:
            body += r"\b"
        followed_by = self._fold_terms(rule.get("followed_by", []))
        if followed_by:
            body += r"(?=\s+(?:" + "|".join(followed_by) + r")\w*)"
        not_followed_by = self._fold_terms(rule.get("not_followed_by", []))
        if not_followed_by:
            body += r"(?!\s+(?:" + "|".join(not_followed_by) + r")\w*)"
        return body

    def _fold_terms(self, terms: list[Any]) -> list[str]:
        folded = (self._fold(self._normalize_query_text(str(term))) for term in terms)
        return [re.escape(term) for term in folded if term]

    def _replace_fold_insensitive(
        self,
        text: str,
        pattern: str,
        replacement: str,
        keep_suffix: bool,
    ) -> tuple[str, bool]:
        """Rewrites diacritic-insensitively while preserving diacritics outside the match.

        Matching runs on a length-preserving folded copy, so match spans map one-to-one
        back onto the original text. With keep_suffix, the matched Turkish suffix
        (group 1) is carried over after the replacement.
        """
        folded = self._fold(text)
        pieces: list[str] = []
        last = 0
        matched = False
        for match in re.finditer(pattern, folded):
            matched = True
            pieces.append(text[last : match.start()])
            pieces.append(replacement)
            if keep_suffix and match.lastindex:
                suffix_start, suffix_end = match.span(1)
                pieces.append(self._harmonize_suffix(text[suffix_start:suffix_end], replacement))
            last = match.end()
        if not matched:
            return text, False
        pieces.append(text[last:])
        return "".join(pieces), True

    def _harmonize_suffix(self, suffix: str, stem: str) -> str:
        """Re-applies Turkish vowel harmony to a suffix carried onto a new stem.

        Each suffix vowel harmonizes with the vowel before it (initially the stem's
        last vowel): a/e follow the 2-way rule, ı/i/u/ü the 4-way rule. This turns
        e.g. "hekim" + "leri" into "doktor" + "ları" instead of "doktorleri".
        """
        prev = next((char for char in reversed(stem) if char in _VOWELS), None)
        if prev is None or not suffix:
            return suffix
        harmonized: list[str] = []
        for char in suffix:
            if char in ("a", "e"):
                char = "a" if prev in _BACK_VOWELS else "e"
            elif char in ("ı", "i", "u", "ü"):
                if prev in ("a", "ı"):
                    char = "ı"
                elif prev in ("e", "i"):
                    char = "i"
                elif prev in ("o", "u"):
                    char = "u"
                else:
                    char = "ü"
            if char in _VOWELS:
                prev = char
            harmonized.append(char)
        return "".join(harmonized)

    def _fold(self, text: str) -> str:
        return text.translate(_TURKISH_FOLD_TABLE)

    def _parse_number(self, token: str) -> int:
        """Parses a digit or spelled-out Turkish count ('uc' -> 3)."""
        if token.isdigit():
            return int(token)
        return _NUMBER_WORDS.get(token, 0)

    def _detect_operations(self, normalized_query: str, rules: dict[str, Any]) -> list[str]:
        """Maps natural action/aggregation wording to canonical operations (LIST, COUNT...)."""
        folded = self._fold(normalized_query)
        operations: list[str] = []
        for operation, terms in rules.get("operations", {}).items():
            for term in terms:
                folded_term = self._fold(self._normalize_query_text(str(term)))
                if not folded_term:
                    continue
                if re.search(r"\b" + re.escape(folded_term) + r"\w*", folded):
                    operations.append(str(operation))
                    break
        return operations

    def _detect_limit_and_order(self, normalized_query: str) -> tuple[int | None, str | None]:
        """Detects 'ilk N' (LIMIT N) and 'son N' (ORDER DESC LIMIT N) ranking phrases.

        'son N gün/hafta/ay/yıl' is temporal wording and is excluded here; it is
        handled by date detection instead.
        """
        folded = self._fold(normalized_query)
        match = re.search(r"\bilk\s+(\d+)\b", folded)
        if match:
            return int(match.group(1)), None
        match = re.search(r"\bson\s+(\d+)\b(?!\s*(?:gun|hafta|ay|yil)\w*)", folded)
        if match:
            return int(match.group(1)), "DESC"
        # Ranking phrases carrying an explicit count: "en çok ... 10 doktoru",
        # "en yoğun 5 bölümü". Date units are temporal wording, not row limits.
        if re.search(r"\ben\s+(cok|fazla|az|yogun|dusuk|yuksek)\b", folded):
            match = re.search(r"\b(\d{1,3})\b(?!\s*(?:gun|hafta|ay|yil|saat)\w*)", folded)
            if match:
                return int(match.group(1)), None
        return None, None

    def _match_ambiguity(
        self, normalized_query: str, rules: dict[str, Any]
    ) -> AmbiguityResult | None:
        folded = self._fold(normalized_query)
        for spec in rules.get("ambiguous", []):
            pattern = self._fold(self._normalize_query_text(str(spec.get("pattern", ""))))
            if not pattern:
                continue
            # Suffix-tolerant: 'performans' must also match 'performansı en yüksek'.
            if re.search(r"\b" + re.escape(pattern) + r"\w*", folded):
                if spec.get("resolvable_by_metrics") and self._resolved_by_explicit_context(folded):
                    # A generic analytical word ("performans") is only ambiguous in
                    # isolation. When the question already states enough explicit,
                    # catalog-resolvable metrics/dimensions to satisfy it (e.g.
                    # "randevu sayısı, gelmeme oranı ve bölüm performansı"), it is
                    # redundant, not undefined — never divert the whole request to
                    # clarification just because this word also appears. Superlative
                    # phrases like "en iyi"/"en başarılı" are NOT flagged this way:
                    # the comparison criterion itself stays undefined regardless of
                    # what else is explicit, so those always keep asking.
                    continue
                return AmbiguityResult(
                    matched_phrase=str(spec.get("pattern", "")),
                    question=str(spec.get("question", "")),
                    options=[str(option) for option in spec.get("options", [])],
                )
        return None

    def _resolved_by_explicit_context(self, folded_question: str) -> bool:
        """True when the question already carries enough explicit, catalog-
        resolvable signal (metrics/dimensions) that a generic analytical word
        elsewhere in the same question is redundant, not undefined.
        """
        from app.semantics import catalog

        metrics = catalog.match_metrics(folded_question)
        dimensions = catalog.match_dimensions(folded_question)
        return len(metrics) >= 2 or (len(metrics) >= 1 and bool(dimensions))

    def _resolve_dates(self, text: str, detected_dates: list[DateRange]) -> str:
        """Replaces relative temporal wording with explicit ISO date ranges.

        The result is the final query sent to SQL generation, so downstream
        nodes never have to interpret relative Turkish dates themselves.
        """
        resolved = text
        for date_range in detected_dates:
            expression = self._fold(self._normalize_query_text(date_range.expression))
            if not expression:
                continue
            if date_range.start_date == date_range.end_date:
                replacement = f"{date_range.start_date.isoformat()} tarihinde"
            else:
                replacement = (
                    f"{date_range.start_date.isoformat()} ile "
                    f"{date_range.end_date.isoformat()} tarihleri arasinda"
                )
            pattern = r"\b" + re.escape(expression) + r"\b"
            resolved, _ = self._replace_fold_insensitive(
                resolved, pattern, replacement, keep_suffix=False
            )
        return re.sub(r"\s+", " ", resolved).strip()

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

        months_ascii = {self._strip_diacritics(name): number for name, number in _MONTHS.items()}
        month_alternatives = "|".join(sorted(months_ascii, key=len, reverse=True))
        explicit_date_pattern = re.compile(
            rf"\b(\d{{1,2}})\s+({month_alternatives})\s+(19\d{{2}}|20\d{{2}})\b"
        )
        explicit_dates = list(explicit_date_pattern.finditer(query_ascii))
        explicit_date_spans = [match.span() for match in explicit_dates]
        month_year_spans = [
            match.span()
            for pattern in (
                rf"\b(20\d{{2}}|19\d{{2}})\s+({month_alternatives})\b",
                rf"\b({month_alternatives})\s+(20\d{{2}}|19\d{{2}})\b",
            )
            for match in re.finditer(pattern, query_ascii)
        ]
        for index in range(0, len(explicit_dates), 2):
            first = explicit_dates[index]
            first_date = date(
                int(first.group(3)), months_ascii[first.group(2)], int(first.group(1))
            )
            if index + 1 >= len(explicit_dates):
                ranges.append(
                    self._date_range(first.group(0), first_date, first_date, "day")
                )
                continue
            second = explicit_dates[index + 1]
            second_date = date(
                int(second.group(3)), months_ascii[second.group(2)], int(second.group(1))
            )
            if second_date < first_date:
                first_date, second_date = second_date, first_date
            expression = query_ascii[first.start() : second.end()]
            ranges.append(self._date_range(expression, first_date, second_date, "custom"))

        # Suffixed forms ("bugunku", "yarinki", "dunku") must also match; the
        # actual matched text is stored so date resolution can replace it.
        # "dun" stays anchored to avoid false positives like "dunya".
        exact_days = [
            (r"\bbugun\w*", today, today, "day"),
            (r"\byarin\w*", today + timedelta(days=1), today + timedelta(days=1), "day"),
            (r"\bdun(ku|den)?\b", today - timedelta(days=1), today - timedelta(days=1), "day"),
        ]
        for pattern, start, end, granularity in exact_days:
            match = re.search(pattern, query_ascii)
            if match:
                ranges.append(self._date_range(match.group(0), start, end, granularity))

        if "bu hafta" in query_ascii:
            start = today - timedelta(days=today.weekday())
            ranges.append(self._date_range("bu hafta", start, start + timedelta(days=6), "week"))

        if "gecen hafta" in query_ascii:
            this_week_start = today - timedelta(days=today.weekday())
            start = this_week_start - timedelta(days=7)
            ranges.append(self._date_range("gecen hafta", start, start + timedelta(days=6), "week"))

        if re.search(r"\bbu ay\w*\b", query_ascii):
            ranges.append(self._month_range("bu ay", today.year, today.month))

        if "gecen ay" in query_ascii:
            year = today.year if today.month > 1 else today.year - 1
            month = today.month - 1 if today.month > 1 else 12
            ranges.append(self._month_range("gecen ay", year, month))

        if "bu yil" in query_ascii:
            ranges.append(self._date_range("bu yil", date(today.year, 1, 1), today, "year"))

        if "gecen yil" in query_ascii or re.search(
            r"\b(?:bir\s+)?onceki\s+yil\w*\b", query_ascii
        ):
            year = today.year - 1
            ranges.append(
                self._date_range("gecen yil", date(year, 1, 1), date(year, 12, 31), "year")
            )

        for match in re.finditer(rf"\bson\s+{_NUMBER_TOKEN}\s+gun\w*\b", query_ascii):
            days = self._parse_number(match.group(1))
            start = today - timedelta(days=max(days - 1, 0))
            ranges.append(self._date_range(match.group(0), start, today, "day"))

        for match in re.finditer(rf"\bonceki\s+{_NUMBER_TOKEN}\s+gun\w*\b", query_ascii):
            days = self._parse_number(match.group(1))
            end = today - timedelta(days=days)
            start = end - timedelta(days=max(days - 1, 0))
            ranges.append(self._date_range(match.group(0), start, end, "day"))

        for match in re.finditer(rf"\bson\s+{_NUMBER_TOKEN}\s+hafta\w*\b", query_ascii):
            weeks = self._parse_number(match.group(1))
            start = today - timedelta(days=max(weeks * 7 - 1, 0))
            ranges.append(self._date_range(match.group(0), start, today, "week"))

        for match in re.finditer(rf"\bonceki\s+{_NUMBER_TOKEN}\s+hafta\w*\b", query_ascii):
            weeks = self._parse_number(match.group(1))
            end = today - timedelta(weeks=weeks)
            start = end - timedelta(days=max(weeks * 7 - 1, 0))
            ranges.append(self._date_range(match.group(0), start, end, "week"))

        for match in re.finditer(rf"\bson\s+{_NUMBER_TOKEN}\s+ay\w*\b", query_ascii):
            months = self._parse_number(match.group(1))
            start = self._shift_months(today, months)
            ranges.append(self._date_range(match.group(0), start, today, "month"))

        for match in re.finditer(rf"\bonceki\s+{_NUMBER_TOKEN}\s+ay\w*\b", query_ascii):
            months = self._parse_number(match.group(1))
            end = self._shift_months(today, months)
            start = self._shift_months(today, months * 2)
            ranges.append(self._date_range(match.group(0), start, end, "month"))

        for match in re.finditer(rf"\bson\s+{_NUMBER_TOKEN}\s+yil\w*\b", query_ascii):
            years = self._parse_number(match.group(1))
            start = self._shift_months(today, years * 12)
            ranges.append(self._date_range(match.group(0), start, today, "year"))

        for match in re.finditer(rf"\bonceki\s+{_NUMBER_TOKEN}\s+yil\w*\b", query_ascii):
            years = self._parse_number(match.group(1))
            end = self._shift_months(today, years * 12)
            start = self._shift_months(today, years * 24)
            ranges.append(self._date_range(match.group(0), start, end, "year"))

        for month_name, month in _MONTHS.items():
            if re.search(rf"\b{self._strip_diacritics(month_name)}\s+ayinda\b", query_ascii):
                ranges.append(self._month_range(f"{month_name} ayinda", today.year, month))

        # Full calendar years, including Turkish case/possessive forms used by
        # short follow-ups (``2024 yılının``, ``2024 yılı``, ``2024 için``,
        # ``2024'te``).  Query normalization has already removed apostrophes.
        for match in re.finditer(
            rf"\b(20\d{{2}}|19\d{{2}})(?:\s+(?:yil\w*|icin|olan\w*|[dty][ae]))?\b"
            rf"(?!\s+(?:{month_alternatives})\b)",
            query_ascii,
        ):
            if self._overlaps_any(
                match.span(), explicit_date_spans + month_year_spans
            ):
                continue
            year = int(match.group(1))
            ranges.append(
                self._date_range(match.group(0), date(year, 1, 1), date(year, 12, 31), "year")
            )

        # Explicit month-year pairs resolve as separate ordered periods.
        for match in re.finditer(
            rf"\b(20\d{{2}}|19\d{{2}})\s+({month_alternatives})\b", query_ascii
        ):
            if self._overlaps_any(match.span(), explicit_date_spans):
                continue
            year, month = int(match.group(1)), months_ascii[match.group(2)]
            ranges.append(self._month_range(match.group(0), year, month))
        for match in re.finditer(
            rf"\b({month_alternatives})\s+(20\d{{2}}|19\d{{2}})\b", query_ascii
        ):
            if self._overlaps_any(match.span(), explicit_date_spans):
                continue
            year, month = int(match.group(2)), months_ascii[match.group(1)]
            ranges.append(self._month_range(match.group(0), year, month))

        # Preserve repeated periods when the user explicitly states both sides.
        # Detector overlap is prevented at the matching sites above.
        return sorted(
            ranges,
            key=lambda item: self._expression_position(query_ascii, item.expression),
        )

    def _overlaps_any(self, span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in occupied)

    def _expression_position(self, query: str, expression: str) -> int:
        position = query.find(self._strip_diacritics(expression))
        return position if position >= 0 else len(query)

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

    def _shift_months(self, base: date, months_back: int) -> date:
        """Returns the date ``months_back`` calendar months before ``base``, day-clamped."""
        total = base.year * 12 + (base.month - 1) - months_back
        year, month_index = divmod(total, 12)
        month = month_index + 1
        day = min(base.day, monthrange(year, month)[1])
        return date(year, month, day)

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
        detected_operations: list[str] | None = None,
    ) -> float:
        score = 0.45
        if entities:
            score += min(0.35, len(entities) * 0.12)
        if detected_dates:
            score += 0.1
        if matched_synonyms:
            score += min(0.1, len(matched_synonyms) * 0.05)
        if detected_operations:
            score += 0.05
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
        operations = list(analysis.detected_operations)
        if analysis.detected_limit is not None:
            operations.append(f"LIMIT {analysis.detected_limit}")
        if analysis.detected_order is not None:
            operations.append(f"ORDER {analysis.detected_order}")
        logger.info(
            "\n================ QUERY ANALYSIS (NLU PIPELINE) ================\n"
            f"Original Query\n{analysis.original_query}\n\n"
            f"Normalized Query\n{analysis.normalized_query}\n\n"
            f"Rewritten Query\n{analysis.rewritten_query}\n\n"
            f"Expanded Query\n{analysis.expanded_query}\n\n"
            "Detected Intent (Operations)\n"
            f"{', '.join(operations) or 'None'}\n\n"
            "Detected Entities\n"
            f"{', '.join(entity.entity_type for entity in analysis.entities) or 'None'}\n\n"
            "Matched Synonyms\n"
            f"{', '.join(analysis.matched_synonyms) or 'None'}\n\n"
            "Date Expressions\n"
            f"{', '.join(self._date_expressions(analysis)) or 'None'}\n\n"
            f"Ambiguous: {'Yes' if analysis.is_ambiguous else 'No'}"
            f"{' (' + analysis.ambiguity.matched_phrase + ')' if analysis.ambiguity else ''}\n\n"
            f"Final Query Sent to SQL Generation\n{analysis.final_query}\n\n"
            f"Confidence\n{analysis.confidence:.2f}\n"
            "================================================",
            extra={
                "original_query": analysis.original_query,
                "normalized_query": analysis.normalized_query,
                "rewritten_query": analysis.rewritten_query,
                "expanded_query": analysis.expanded_query,
                "final_query": analysis.final_query,
                "detected_operations": operations,
                "entities": [entity.entity_type for entity in analysis.entities],
                "matched_synonyms": analysis.matched_synonyms,
                "date_expressions": self._date_expressions(analysis),
                "is_ambiguous": analysis.is_ambiguous,
                "confidence": analysis.confidence,
            },
        )

    def _date_expressions(self, analysis: QueryAnalysis) -> list[str]:
        return [date_range.expression for date_range in analysis.detected_dates]
