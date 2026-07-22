"""Grounded analytical value-resolution layer (AI-INTELLIGENCE-016).

Resolves free-text filter mentions (branch/doctor/department/service/
category/appointment source/status/type/nationality/gender) against real,
approved distinct database values (`app.database_intelligence.value_catalog`).
Never invents a filter: an unmatched or ambiguous mention degrades to
`grounded=False` + `clarification_required=True` instead of a guessed LIKE
predicate.

Two layers, independently testable:
  - `resolve_value()` — pure matching against a pre-fetched candidate list.
  - `ValueResolver.resolve()` — fetches candidates from `ValueCatalog` (DB)
    then calls `resolve_value()`.
Phrase extraction (`extract_candidate_phrases`) is a separate, also-pure step
that finds candidate raw text spans in a question, keyed by field.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from app.database_intelligence.value_catalog import FIELD_COLUMNS, ValueCatalog
from app.semantics.view_mapping import fold

_PUNCT_PATTERN = re.compile(r"[^\w\s]", re.UNICODE)
_WS_PATTERN = re.compile(r"\s+")
_STRIP_CHARS = ".,;:!?"

_FUZZY_THRESHOLD = 0.82
_FUZZY_MARGIN = 0.08  # score gap within which two candidates are "too close to call"

# Curated code aliases for fields whose grounded values are short codes rather
# than free text (CinsiyetId: E/K/D) — matched before catalog lookup.
_GENDER_ALIASES: dict[str, str] = {
    "erkek": "E",
    "bay": "E",
    "erkek hasta": "E",
    "kadin": "K",
    "bayan": "K",
    "kadin hasta": "K",
    "diger": "D",
    "belirsiz": "D",
    "bilinmiyor": "D",
}

# Cue-word ROOTS (folded), matched via startswith against each token to
# absorb Turkish suffix inflection ("bölümündeki", "şubesinde", ...) without
# enumerating every inflected form. Sourced from the same synonym vocabulary
# as app/resources/column_intelligence.json. Roots ending in "k" also carry
# their consonant-mutation variant (k->ğ before a vowel-initial suffix,
# e.g. "kaynaktan" is ungrammatical — the real word is "kaynağından",
# folding to "kaynagindan") — without it, "Telefon kaynağından gelen
# randevular" would silently fail to cue appointment_source at all.
_FIELD_CUE_ROOTS: dict[str, tuple[str, ...]] = {
    "branch": ("sube", "hastane", "lokasyon", "merkez"),
    "department": ("bolum", "brans", "klinik", "poliklinik"),
    "service": ("hizmet", "islem"),
    "category": ("kategori",),
    "appointment_source": ("kaynak", "kaynag"),
    "doctor": ("doktor", "hekim", "uzman"),
    "appointment_status": ("durum",),
    "appointment_type": ("tip", "tur"),
    "nationality": ("uyruk", "uyrug"),
    "gender": ("cinsiyet",),
}

# Quantifier/scope words that must never anchor a candidate phrase — these are
# generic-scope wording ("tüm", "bütün", ...), not a real value mention.
_GENERIC_QUANTIFIERS = {
    "tum", "tüm", "butun", "bütün", "her", "genel", "geneli", "genelinde",
}

# AI-INTELLIGENCE-017 regression fix: bare domain/dimension nouns (folded
# roots, matched via startswith) must NEVER become a candidate filter value,
# no matter how they're capitalized or positioned. Without this guard, "Randevu
# durumlarının dağılımını göster" walked back from the "durum*" cue straight
# into "Randevu" (capitalized only because it starts the sentence) and treated
# it as a candidate status VALUE — the dimension noun that introduces the cue
# is not itself a value. Union of _GENERIC_QUANTIFIERS and every field's own
# cue roots (a dimension word can never be another field's value either) —
# derived directly from _FIELD_CUE_ROOTS so the two can never drift apart.
_NEVER_CANDIDATE_ROOTS: tuple[str, ...] = tuple(
    sorted(
        _GENERIC_QUANTIFIERS
        | {"randevu", "hasta"}
        | {root for roots in _FIELD_CUE_ROOTS.values() for root in roots}
    )
)

# Distribution/grouping wording (folded) — when this appears near a field's
# own dimension noun, the phrase names a GROUPING, not a filter value
# ("randevu durumlarının dağılımı", "şubelere göre"). See classify_value_intent().
_GROUPING_MARKERS: tuple[str, ...] = (
    "dagilim", "bazinda", "bazli", "gore", "kirilim", "gruplandir", "gruplarina",
)

_FILTER_INTENT_MARKERS: tuple[str, ...] = (
    "sadece", "sinirla", "sinirlandir", "filtrele", "olan", "icin",
)

# Aggregate "use everything / clear this filter" clarification replies (item
# 5). Matched against FOLDED (diacritic-stripped, lowercased) text only.
ALL_REPLY_PATTERN = re.compile(r"\b(hepsini|hepsi|tumu|tamamini|tamami|butununu)\b")

# Ordinal clarification replies ("ilkini", "ikincisini", ...) -> 0-based index.
ORDINAL_REPLY_INDEX: dict[str, int] = {
    "ilkini": 0, "ilk": 0, "birincisini": 0, "birinci": 0,
    "ikincisini": 1, "ikinci": 1,
    "ucuncusunu": 2, "ucuncu": 2,
    "dorduncusunu": 3, "dorduncu": 3,
}

_FIELD_LABELS_TR: dict[str, str] = {
    "branch": "şube",
    "department": "bölüm",
    "service": "hizmet",
    "category": "kategori",
    "appointment_source": "kaynak",
    "doctor": "doktor",
    "appointment_status": "durum",
    "appointment_type": "randevu tipi",
    "nationality": "uyruk",
    "gender": "cinsiyet",
}

_MAX_PHRASE_TOKENS = 4


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Deduplicates by canonical normalized form, keeping the first-seen
    original Turkish text (item 4: no duplicate clarification bullets)."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = normalize(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def normalize(text_value: str) -> str:
    """Turkish-safe normalization for matching only — original casing/diacritics
    are preserved separately in `ResolvedValue.original_text`/`matched_value`."""
    folded = fold(text_value)
    no_punct = _PUNCT_PATTERN.sub(" ", folded)
    return _WS_PATTERN.sub(" ", no_punct).strip()


@dataclass
class ResolvedValue:
    """Outcome of resolving one candidate text span against grounded values."""

    field: str
    original_text: str
    normalized_text: str
    matched_value: str | None
    match_type: str  # exact|normalized_exact|alias|prefix|fuzzy|no_match|ambiguous
    confidence: float
    alternatives: list[str] = dataclass_field(default_factory=list)
    grounded: bool = False
    clarification_required: bool = False


def resolve_value(field_name: str, original_text: str, candidates: list[str]) -> ResolvedValue:
    """Pure matcher: `original_text` against a pre-fetched grounded `candidates` list.

    Never fuzzy-matches into an unrestricted guess — a low-confidence or
    multi-way-tied match degrades to `no_match`/`ambiguous`, never a forced
    single answer.
    """
    normalized_input = normalize(original_text)

    if field_name == "gender" and normalized_input in _GENDER_ALIASES:
        alias_code = _GENDER_ALIASES[normalized_input]
        if not candidates or alias_code in candidates:
            return ResolvedValue(
                field=field_name,
                original_text=original_text,
                normalized_text=normalized_input,
                matched_value=alias_code,
                match_type="alias",
                confidence=0.95,
                grounded=True,
            )

    if not candidates:
        return ResolvedValue(
            field=field_name,
            original_text=original_text,
            normalized_text=normalized_input,
            matched_value=None,
            match_type="no_match",
            confidence=0.0,
            grounded=False,
            clarification_required=True,
        )

    stripped_original = original_text.strip()
    exact = [c for c in candidates if c == stripped_original]
    if len(exact) == 1:
        return ResolvedValue(
            field=field_name,
            original_text=original_text,
            normalized_text=normalized_input,
            matched_value=exact[0],
            match_type="exact",
            confidence=1.0,
            grounded=True,
        )

    normalized_map: dict[str, list[str]] = {}
    for candidate in candidates:
        normalized_map.setdefault(normalize(candidate), []).append(candidate)

    normalized_exact = sorted(set(normalized_map.get(normalized_input, [])))
    if len(normalized_exact) == 1:
        return ResolvedValue(
            field=field_name,
            original_text=original_text,
            normalized_text=normalized_input,
            matched_value=normalized_exact[0],
            match_type="normalized_exact",
            confidence=0.95,
            grounded=True,
        )
    if len(normalized_exact) > 1:
        return ResolvedValue(
            field=field_name,
            original_text=original_text,
            normalized_text=normalized_input,
            matched_value=None,
            match_type="ambiguous",
            confidence=0.5,
            alternatives=_dedupe_preserve_order(normalized_exact),
            grounded=False,
            clarification_required=True,
        )

    prefix_matches = sorted(
        {
            candidate
            for norm, group in normalized_map.items()
            for candidate in group
            if norm.startswith(normalized_input) or normalized_input.startswith(norm)
        }
    )
    if len(prefix_matches) == 1:
        return ResolvedValue(
            field=field_name,
            original_text=original_text,
            normalized_text=normalized_input,
            matched_value=prefix_matches[0],
            match_type="prefix",
            confidence=0.85,
            grounded=True,
        )
    if len(prefix_matches) > 1:
        return ResolvedValue(
            field=field_name,
            original_text=original_text,
            normalized_text=normalized_input,
            matched_value=None,
            match_type="ambiguous",
            confidence=0.5,
            alternatives=_dedupe_preserve_order(prefix_matches)[:5],
            grounded=False,
            clarification_required=True,
        )

    scored = sorted(
        (
            (difflib.SequenceMatcher(None, normalized_input, norm).ratio(), group[0])
            for norm, group in normalized_map.items()
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if scored and scored[0][0] >= _FUZZY_THRESHOLD:
        best_score, best_value = scored[0]
        close = sorted(
            {
                value
                for score, value in scored
                if value != best_value and best_score - score <= _FUZZY_MARGIN
            }
        )
        if close:
            return ResolvedValue(
                field=field_name,
                original_text=original_text,
                normalized_text=normalized_input,
                matched_value=None,
                match_type="ambiguous",
                confidence=0.6,
                alternatives=_dedupe_preserve_order(sorted({best_value, *close})),
                grounded=False,
                clarification_required=True,
            )
        return ResolvedValue(
            field=field_name,
            original_text=original_text,
            normalized_text=normalized_input,
            matched_value=best_value,
            match_type="fuzzy",
            confidence=round(best_score, 2),
            grounded=True,
        )

    return ResolvedValue(
        field=field_name,
        original_text=original_text,
        normalized_text=normalized_input,
        matched_value=None,
        match_type="no_match",
        confidence=0.0,
        alternatives=_dedupe_preserve_order([value for _score, value in scored])[:5],
        grounded=False,
        clarification_required=True,
    )


def build_clarification_headline(resolved: ResolvedValue) -> str:
    """The lead clarification SENTENCE only — no embedded bullet list.

    Callers that render `alternatives`/`options` separately (e.g.
    GenerateClarificationNode, which already renders its own bullet list
    from `AmbiguityResult.options`) must use this, not
    `build_clarification_message()`, to avoid rendering every option twice.
    """
    label = _FIELD_LABELS_TR.get(resolved.field, resolved.field)
    if resolved.match_type == "ambiguous" and resolved.alternatives:
        return (
            f"'{resolved.original_text}' için birden fazla {label} bulundu. "
            "Hangisini kullanmalıyım?"
        )
    if resolved.match_type == "no_match" and resolved.alternatives:
        return (
            f"'{resolved.original_text}' değerine uygun bir {label} bulunamadı. "
            "Şunlardan birini mi kastettiniz?"
        )
    return f"'{resolved.original_text}' değerine uygun bir {label} bulunamadı."


def build_clarification_message(resolved: ResolvedValue) -> str:
    """Full Turkish clarification text (headline + bullet list) for contexts
    that render a single combined string (e.g. `ResolvedFilterPlan.clarification_message`,
    a diagnostic field with no separate options renderer)."""
    headline = build_clarification_headline(resolved)
    if resolved.alternatives:
        options = "\n".join(f"- {option}" for option in resolved.alternatives[:5])
        return f"{headline}\n{options}"
    return headline


def classify_value_intent(question: str, field_name: str) -> str:
    """Typed verdict (item 3): none | filter | grouping | ambiguous.

    'filter' when a genuine value-cue phrase survives extraction for this
    field; 'grouping' when the field's dimension noun appears near a
    distribution/grouping marker ("dağılımı", "bazında", "göre", ...) with no
    surviving value candidate; 'none' otherwise. This module never returns
    'ambiguous' here — that verdict is reserved for a resolved *match*
    (`resolve_value` returning match_type="ambiguous"), not the pre-resolution
    phrase-extraction stage.
    """
    if field_name in extract_candidate_phrases(question):
        return "filter"
    folded = fold(question)
    roots = _FIELD_CUE_ROOTS.get(field_name, ())
    has_dimension_mention = any(
        token.startswith(root) for root in roots for token in folded.split()
    )
    if has_dimension_mention and any(marker in folded for marker in _GROUPING_MARKERS):
        return "grouping"
    return "none"


def extract_candidate_phrases(question: str) -> dict[str, list[str]]:
    """Finds raw candidate value phrases per field from cue-word context.

    A candidate is the capitalized/proper-noun-like token run immediately
    preceding a field cue word ("TEST ASM Gebze şubesi" -> branch candidate
    "TEST ASM Gebze"). Generic scope wording ("tüm", "bütün", ...) never forms
    a candidate — the walk stops there, so "tüm aile sağlığı merkezleri"
    yields no branch candidate.

    Also supports the bare "İçin" pattern for branch ("Gebze için göster.",
    "TEST ASM Gebze için ... göster.") as a fallback when no cue word is
    present — the immediately preceding token run must still be capitalized,
    which naturally excludes lowercase generic-scope phrasing.
    """
    tokens = question.split()
    folded_tokens = [fold(token) for token in tokens]
    results: dict[str, list[str]] = {}

    def _walk_back(end_index: int) -> str | None:
        phrase_tokens: list[str] = []
        j = end_index
        while j >= 0 and len(phrase_tokens) < _MAX_PHRASE_TOKENS:
            original = tokens[j].strip(_STRIP_CHARS)
            folded_word = folded_tokens[j].strip(_STRIP_CHARS)
            if not original or not original[0].isupper():
                break
            if any(folded_word.startswith(root) for root in _NEVER_CANDIDATE_ROOTS):
                break
            phrase_tokens.insert(0, original)
            j -= 1
        return " ".join(phrase_tokens) if phrase_tokens else None

    for field_name, roots in _FIELD_CUE_ROOTS.items():
        for index, folded_token in enumerate(folded_tokens):
            cleaned = folded_token.strip(_STRIP_CHARS)
            if not any(cleaned.startswith(root) for root in roots):
                continue
            phrase = _walk_back(index - 1)
            if phrase:
                results.setdefault(field_name, []).append(phrase)

    if "branch" not in results:
        for index, folded_token in enumerate(folded_tokens):
            if folded_token.strip(_STRIP_CHARS) != "icin":
                continue
            phrase = _walk_back(index - 1)
            if phrase:
                results.setdefault("branch", []).append(phrase)

    # Code-backed gender values are already grounded by `_GENDER_ALIASES`.
    # They commonly appear after the dimension noun ("kadın hastalarla
    # sınırla"), so the proper-noun walk-back used for database text values
    # cannot find them.  A single alias plus explicit filter wording is a value
    # filter; multiple aliases ("kadın ve erkek oranı") describe cohorts and
    # must remain a grouping/calculation request.
    folded_question = fold(question)
    matched_gender_aliases = [
        alias
        for alias in _GENDER_ALIASES
        if re.search(rf"\b{re.escape(alias)}\b", folded_question)
    ]
    matched_gender_codes = {_GENDER_ALIASES[alias] for alias in matched_gender_aliases}
    if (
        len(matched_gender_codes) == 1
        and any(marker in folded_question for marker in _FILTER_INTENT_MARKERS)
    ):
        shortest_alias = min(matched_gender_aliases, key=len)
        results["gender"] = [shortest_alias]

    return results


class ValueResolver:
    """Fetches grounded candidates from `ValueCatalog` and resolves a mention."""

    def __init__(self, catalog: ValueCatalog | None = None) -> None:
        self.catalog = catalog or ValueCatalog()

    async def resolve(self, field_name: str, original_text: str) -> ResolvedValue:
        column, tier = FIELD_COLUMNS.get(field_name, (None, None))
        if column is None:
            return ResolvedValue(
                field=field_name,
                original_text=original_text,
                normalized_text=normalize(original_text),
                matched_value=None,
                match_type="no_match",
                confidence=0.0,
                grounded=False,
                clarification_required=True,
            )
        if tier == "high":
            candidates = await self.catalog.search_candidates(field_name, original_text)
        else:
            candidates = await self.catalog.get_distinct_values(field_name)
        return resolve_value(field_name, original_text, candidates)
