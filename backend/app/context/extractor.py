import re

from app.context.models import ExtractedSignals

# Length-preserving Turkish diacritic fold so match spans on the folded text
# map one-to-one back onto the original question during rewrites.
_FOLD_TABLE = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "I": "i",
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

_MONTH_NAMES = "ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik"

# Spelled-out Turkish counts, folded (ç->c, ü->u...). "Son üç ay" must be
# detected exactly like "son 3 ay" — a digit-only pattern here previously let
# spelled-number periods slip through undetected, which meant the current
# question was treated as having NO explicit date and inherited context got
# incorrectly prepended (a spelled-number multi-period question was silently
# invisible to this detector).
_NUMBER_WORD = r"(?:\d+|bir|iki|uc|dort|bes|alti|yedi|sekiz|dokuz|on)"

# Temporal expressions, longest/most-specific first, matched on folded text.
# Each entry is (regex, canonical) — canonical=None keeps the matched span.
# Canonical forms are what the downstream NLU date detector recognizes, so
# suffixed variants ("bugünkü", "bu ayki") are normalized before re-injection.
_DATE_PATTERNS = [
    (rf"\bson\s+{_NUMBER_WORD}\s+(?:gun|hafta|ay|yil)\w*", None),
    (rf"\bonceki\s+{_NUMBER_WORD}\s+(?:gun|hafta|ay|yil)\w*", None),
    (r"\bgecen\s+hafta\b", "gecen hafta"),
    (r"\bgecen\s+ay\b", "gecen ay"),
    (r"\bgecen\s+yil\b", "gecen yil"),
    (r"\bbu\s+hafta\b", "bu hafta"),
    (r"\bbu\s+ay\w*\b", "bu ay"),
    (r"\bbu\s+yil\b", "bu yil"),
    (r"\bbugun\w*\b", "bugun"),
    (r"\bdun\b", "dun"),
    (r"\byarin\b", "yarin"),
    (rf"\b(?:{_MONTH_NAMES})\s+ayinda\b", None),
    (r"\b(?:19|20)\d{2}\s+yilinda\b", None),
]

# Folded department keyword -> canonical display name (values as stored in the
# demo hospital database).
_DEPARTMENTS = {
    "kardiyoloji": "Kardiyoloji",
    "dahiliye": "Dahiliye",
    "ortopedi": "Ortopedi",
    "cildiye": "Cildiye",
    "dermatoloji": "Cildiye",
    "goz": "Goz Hastaliklari",
    "kulak burun bogaz": "Kulak Burun Bogaz",
    "kbb": "Kulak Burun Bogaz",
    "noroloji": "Noroloji",
    "genel cerrahi": "Genel Cerrahi",
    "kadin dogum": "Kadin Dogum",
    "jinekoloji": "Kadin Dogum",
    "cocuk": "Cocuk Sagligi",
    "pediatri": "Cocuk Sagligi",
    "psikiyatri": "Psikiyatri",
    "uroloji": "Uroloji",
    "acil": "Acil",
}

# Folded stem -> canonical entity type. Kept intentionally small and local so
# the context module has no dependency on the NLU synonym configuration.
_ENTITY_TERMS = {
    "doktor": "Doctor",
    "hekim": "Doctor",
    "uzman": "Doctor",
    "hasta": "Patient",
    "randevu": "Appointment",
    "muayene": "Appointment",
    "recete": "Prescription",
    "ilac": "Prescription",
    "tani": "Diagnosis",
    "teshis": "Diagnosis",
    "fatura": "Invoice",
}

_DEPARTMENT_WORDS = ("bolum", "klinik", "poliklinik", "brans", "servis")

# Referential pronouns handled by the resolver. Ordered longest-first so
# multi-word forms win over their single-word prefixes.
_PRONOUN_PATTERNS = [
    r"\bo\s+bolum\w*",
    r"\bbu\s+bolum\w*",
    r"\bayni\s+bolum\w*",
    r"\bo\s+doktor\w*",
    r"\bayni\s+doktor\w*",
    r"\bo\s+hasta\w*",
    r"\bbunlardan\b",
    r"\bonlardan\b",
    r"\bsunlardan\b",
    r"\bbunlarin\b",
    r"\bonlarin\b",
    r"\bbunlari\b",
    r"\bonlari\b",
    r"\bbunlar\b",
    r"\bonlar\b",
    r"\bsunlar\b",
]

# Content-token threshold below which a question is treated as too short to be
# a complete, independent question — a deterministic proxy for "missing subject
# / clearly depends on the previous turn". Chosen so genuine short follow-ups
# ("Kaç hasta muayene edildi?", "En yoğun bölüm hangisi?" — both 4 tokens) stay
# elliptical while a fully-formed independent question that merely happens to
# contain one analytical word ("Kadın hastaların yaş dağılımını göster" — 5
# tokens) does not.
_ELLIPTICAL_MAX_TOKENS = 4

_RANKING_CUES = ("en yogun", "en cok", "en fazla", "en az", "en yuksek", "en dusuk")
_COMPARISON_CUES = ("karsilastir", "kiyasla", "farki", "gore dagilim")
_TREND_CUES = ("trend", "degisim", "aylara gore", "gunlere gore", "artis", "azalis")
_COUNT_CUES = ("kac", "sayisi", "sayis", "toplam", "ortalama", "adet")
_LIST_CUES = ("listele", "goster", "getir", "goruntule", "hangileri")
_ANALYTICAL_CUES = (
    "kac",
    "sayis",
    "toplam",
    "ortalama",
    "yogun",
    "fazla",
    "hangisi",
    "hangi",
    "kim",
    "oran",
    "dagilim",
    "trend",
    "karsilastir",
    "kiyasla",
    "en ",
)

# Filler tokens ignored when deciding whether a question is a date-only
# follow-up such as "Peki geçen ay?".
_FILLER_TOKENS = {
    "peki",
    "ya",
    "ve",
    "icin",
    "nasil",
    "olur",
    "olsun",
    "aynisi",
    "ayni",
    "sey",
    "seyi",
    "olarak",
    "da",
    "de",
}


class ContextExtractor:
    """Deterministic signal extractor feeding the conversational context engine."""

    def extract(self, question: str) -> ExtractedSignals:
        folded = self._fold(question)

        date_expression = self._detect_date(question, folded)
        department = self._detect_department(folded)
        entity_types = self._detect_entities(folded)
        pronouns = self._detect_pronouns(folded)
        analysis_type = self._detect_analysis_type(folded)
        is_analytical = any(cue in folded for cue in _ANALYTICAL_CUES)
        asks_department = any(re.search(rf"\b{word}\w*", folded) for word in _DEPARTMENT_WORDS)
        is_date_only = self._is_date_only_followup(folded, date_expression)
        is_elliptical = self._is_elliptical(folded)

        return ExtractedSignals(
            date_expression=date_expression,
            department=department,
            entity_types=entity_types,
            pronouns=pronouns,
            analysis_type=analysis_type,
            is_analytical=is_analytical,
            asks_department=asks_department,
            is_date_only_followup=is_date_only,
            is_elliptical=is_elliptical,
        )

    def fold(self, text: str) -> str:
        """Public folding helper shared with the resolver."""
        return self._fold(text)

    def _fold(self, text: str) -> str:
        lowered = text.replace("İ", "i").lower().replace("̇", "")
        folded = lowered.translate(_FOLD_TABLE)
        stripped = re.sub(r"[^\w\s-]", " ", folded)
        return re.sub(r"\s+", " ", stripped).strip()

    def _detect_date(self, original: str, folded: str) -> str | None:
        for pattern, canonical in _DATE_PATTERNS:
            match = re.search(pattern, folded)
            if match:
                return canonical or re.sub(r"\s+", " ", match.group(0))
        return None

    def _detect_department(self, folded: str) -> str | None:
        for term, canonical in _DEPARTMENTS.items():
            if re.search(rf"\b{re.escape(term)}\w*", folded):
                return canonical
        return None

    def _detect_entities(self, folded: str) -> list[str]:
        entities: list[str] = []
        for term, canonical in _ENTITY_TERMS.items():
            if canonical in entities:
                continue
            if re.search(rf"\b{re.escape(term)}\w*", folded):
                entities.append(canonical)
        return entities

    def _detect_pronouns(self, folded: str) -> list[str]:
        pronouns: list[str] = []
        for pattern in _PRONOUN_PATTERNS:
            match = re.search(pattern, folded)
            if match:
                pronouns.append(match.group(0))
        return pronouns

    def _detect_analysis_type(self, folded: str) -> str | None:
        if any(cue in folded for cue in _COMPARISON_CUES):
            return "comparison"
        if any(cue in folded for cue in _TREND_CUES):
            return "trend"
        if any(cue in folded for cue in _RANKING_CUES):
            return "ranking"
        if any(cue in folded for cue in _COUNT_CUES):
            return "count"
        if any(cue in folded for cue in _LIST_CUES):
            return "list"
        return None

    def _is_elliptical(self, folded: str) -> bool:
        """True when the question has few enough content tokens to plausibly be
        incomplete without previous-turn context (see `_ELLIPTICAL_MAX_TOKENS`)."""
        tokens = [token for token in folded.split() if token not in _FILLER_TOKENS]
        return len(tokens) <= _ELLIPTICAL_MAX_TOKENS

    def _is_date_only_followup(self, folded: str, date_expression: str | None) -> bool:
        """True when the question adds only a new temporal filter ('Peki geçen ay?')."""
        if not date_expression:
            return False
        remainder = folded
        for pattern, _ in _DATE_PATTERNS:
            remainder = re.sub(pattern, " ", remainder)
        tokens = [token for token in remainder.split() if token not in _FILLER_TOKENS]
        return not tokens
