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
from collections.abc import Collection
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

# Colloquial / abbreviated department names users actually type, mapped to the
# CLINICAL wording the real department values are built from. These are only
# search hints: each expansion is matched against the grounded candidate list
# through the normal prefix/fuzzy pipeline below, so a term with no real
# department behind it still degrades to `no_match` and is never invented.
# Without these, "kalp branşında", "KBB", "pediatri" and "kadın doğum" resolved
# to nothing and the question silently answered over EVERY department (Codex
# live UI testing, 2026-07-31).
_DEPARTMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "kalp": ("kardiyoloji",),
    "kalp damar": ("kalp ve damar cerrahisi", "kardiyoloji"),
    "kbb": ("kulak burun bogaz",),
    "kulak burun": ("kulak burun bogaz",),
    "pediatri": ("cocuk sagligi", "cocuk"),
    "cocuk doktoru": ("cocuk sagligi", "cocuk"),
    "kadin dogum": ("kadin hastaliklari", "kadin dogum"),
    "kadin dogumu": ("kadin hastaliklari", "kadin dogum"),
    "dogum": ("kadin hastaliklari", "kadin dogum"),
    "jinekoloji": ("kadin hastaliklari", "kadin dogum"),
    "goz": ("goz hastaliklari", "goz"),
    "cildiye": ("deri", "dermatoloji"),
    "dermatoloji": ("deri", "dermatoloji"),
    "dahiliye": ("ic hastaliklari", "dahiliye"),
    "beyin cerrahi": ("beyin ve sinir cerrahisi", "norosirurji"),
    "norolojik": ("noroloji",),
    "ortopedi": ("ortopedi",),
    "uroloji": ("uroloji",),
    "onkoloji": ("onkoloji",),
    "psikiyatri": ("psikiyatri", "ruh sagligi"),
}

# `Uyruk` stores COUNTRY names ("Türkiye", "Almanya", "Rusya Fed."), but people
# ask with the DEMONYM ("türk hasta", "Suriyeli hastalar"). A demonym carries no
# "uyruk" cue word and is not capitalised, so neither the proper-noun walk-back
# nor the cue-root scan ever produced a candidate: "kaç adet türk hasta var"
# dropped the nationality entirely and answered "1.683.876 randevu" — the total
# over EVERY nationality, presented as if it were the answer (live UI testing,
# 2026-08-03).
#
# Each expansion is the COUNTRY name, never the demonym, and is matched by
# containment against the grounded value list — so "turk" resolves to "Türkiye"
# without also matching "Türkmenistan", which the bare demonym would.
# Search hints only: a demonym with no real nationality behind it still degrades
# to `no_match` and is never invented.
_NATIONALITY_ALIASES: dict[str, tuple[str, ...]] = {
    "turk": ("turkiye",),
    "turkiyeli": ("turkiye",),
    "suriyeli": ("suriye",),
    "alman": ("almanya",),
    "rus": ("rusya",),
    "bulgar": ("bulgaristan",),
    "romen": ("romanya",),
    "gurcu": ("gurcistan",),
    "azeri": ("azerbaycan",),
    "kazak": ("kazakistan",),
    "ozbek": ("ozbekistan",),
    "kirgiz": ("kirgizistan",),
    "turkmen": ("turkmenistan",),
    "ukraynali": ("ukrayna",),
    "iranli": ("iran",),
    "irakli": ("irak",),
    "libyali": ("libya",),
    "cezayirli": ("cezayir",),
    "arnavut": ("arnavutluk",),
    "ingiliz": ("ingiltere",),
    "amerikali": ("abd",),
    "kanadali": ("kanada",),
    "sirp": ("sirbistan",),
    "nijeryali": ("nijerya",),
    "etiyopyali": ("etiyopya",),
    "kamerunlu": ("kamerun",),
    "moldovali": ("moldova",),
    "kosovali": ("kosova",),
    "bahreynli": ("bahreyn",),
    "gabonlu": ("gabon",),
}

# Fields whose colloquial wording needs expanding before it can be grounded.
_ALIASES_BY_FIELD: dict[str, dict[str, tuple[str, ...]]] = {
    "department": _DEPARTMENT_ALIASES,
    "nationality": _NATIONALITY_ALIASES,
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
    "department": ("bolum", "brans", "klinik", "poliklinik", "servis", "departman"),
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
    "tum",
    "tüm",
    "butun",
    "bütün",
    "her",
    "genel",
    "geneli",
    "genelinde",
}

# "genel" is almost always the generic-scope word above ("genel olarak",
# "tüm şubeler genelinde") - but it is also the literal first word of a real
# department name, "Genel Cerrahi" (General Surgery). Blocking it
# unconditionally truncated "Genel Cerrahi bölümünde ..." down to the bare
# fragment "Cerrahi", which then matched several unrelated *Cerrahi*
# departments (Çocuk Cerrahisi, Göğüs Cerrahisi, ...) as equally-scored
# candidates and forced an unnecessary clarification (2026-07-24, found via
# the live benchmark). Keyed by the token already accepted to genel's right.
_GENERIC_QUANTIFIER_EXCEPTIONS: dict[str, set[str]] = {
    "genel": {"cerrahi"},
}

# Interrogative/demonstrative words (folded, matched as EXACT tokens — a
# startswith root would swallow real values like "Nefroloji" via "ne", or
# "Onkoloji" via an "on" root for the pronoun "o"). These are capitalized in
# sentence-initial position ("Kaç doktor var?", "Hangi bölüm ...?", "Bunu
# şubeye göre kır") and must never be mistaken for a proper-noun value
# mention. The nominative demonstratives ("bu"/"şu"/"o") were already here;
# their inflected accusative/genitive/dative/locative/ablative/instrumental
# forms were not, so "Bunu şubeye göre kır" walked back from the "şube" cue
# straight into "Bunu" and asked the user to disambiguate it as a BRANCH
# NAME ("'Bunu' değerine uygun bir şube bulunamadı...") instead of resolving
# as a follow-up pronoun (2026-07-27, live multi-turn testing). This is the
# value-CANDIDATE stopset only - distinct from extractor._PRONOUN_PATTERNS
# (follow-up referent resolution), which deliberately excludes bare "bunu"/
# "onu" for unrelated reasons (see composite-department-grounding memory,
# Phase 10) - adding them here carries none of that risk, it only stops them
# from being treated as a literal filter value.
_QUESTION_WORDS = {
    "kac",
    "kacar",
    "kacinci",
    "hangi",
    "hangisi",
    "hangileri",
    "ne",
    "neler",
    "nedir",
    "neyi",
    "neye",
    "kim",
    "kimler",
    "kimin",
    "nasil",
    "neden",
    "nicin",
    "niye",
    "nerede",
    "nereye",
    "nereden",
    "nereli",
    "nere",
    "neresi",
    "bu",
    "su",
    "o",
    "iste",
    "sonuc",
    "sonucu",
    "sonucun",
    "sonuca",
    "sonucta",
    "sonuctan",
    "bunu",
    "bunun",
    "buna",
    "bunda",
    "bundan",
    "bununla",
    "bunlar",
    "bunlari",
    "bunlarin",
    "bunlara",
    "bunlarda",
    "bunlardan",
    "bunlarla",
    "sunu",
    "sunun",
    "suna",
    "sunda",
    "sundan",
    "sununla",
    "sunlar",
    "sunlari",
    "sunlarin",
    "sunlara",
    "sunlarda",
    "sunlardan",
    "sunlarla",
    "onu",
    "onun",
    "ona",
    "onda",
    "ondan",
    "onunla",
    "onlar",
    "onlari",
    "onlarin",
    "onlara",
    "onlarda",
    "onlardan",
    "onlarla",
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

# A SHORT root cannot be prefix-matched: appointment_type's "tur" swallowed
# every value beginning with it, so "Türkiye uyruklu hastaların randevu sayısı"
# extracted no nationality at all and silently answered over EVERY nationality,
# and "Turgut Özal Şubesi" was truncated to "Özal". Long roots keep prefix
# matching because that is what absorbs inflection ("bölümündeki",
# "durumlarının"); at three or four letters the false positives outnumber it.
_MIN_PREFIX_ROOT_LENGTH = 5


def _is_dimension_noun(folded_word: str) -> bool:
    """Whether a token is a dimension noun rather than a value."""
    return any(
        folded_word == root
        or (len(root) >= _MIN_PREFIX_ROOT_LENGTH and folded_word.startswith(root))
        for root in _NEVER_CANDIDATE_ROOTS
    )


# Distribution/grouping wording (folded) — when this appears near a field's
# own dimension noun, the phrase names a GROUPING, not a filter value
# ("randevu durumlarının dağılımı", "şubelere göre"). See classify_value_intent().
_GROUPING_MARKERS: tuple[str, ...] = (
    "dagilim",
    "bazinda",
    "bazli",
    "gore",
    "kirilim",
    "gruplandir",
    "gruplarina",
)

_FILTER_INTENT_MARKERS: tuple[str, ...] = (
    "sadece",
    "sinirla",
    "sinirlandir",
    "filtrele",
    "olan",
    "icin",
)

# Aggregate "use everything / clear this filter" clarification replies (item
# 5). Matched against FOLDED (diacritic-stripped, lowercased) text only.
ALL_REPLY_PATTERN = re.compile(r"\b(hepsini|hepsi|tumu|tamamini|tamami|butununu)\b")

# Ordinal clarification replies ("ilkini", "ikincisini", ...) -> 0-based index.
ORDINAL_REPLY_INDEX: dict[str, int] = {
    "ilkini": 0,
    "ilk": 0,
    "birincisini": 0,
    "birinci": 0,
    "ikincisini": 1,
    "ikinci": 1,
    "ucuncusunu": 2,
    "ucuncu": 2,
    "dorduncusunu": 3,
    "dorduncu": 3,
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


def _resolve_by_alias(
    field_name: str,
    original_text: str,
    normalized_input: str,
    normalized_map: dict[str, list[str]],
    expansions: tuple[str, ...],
) -> ResolvedValue | None:
    """Grounds a colloquial term by looking for its expansion INSIDE real values.

    Returns None when no expansion is behind the term, so the caller continues
    with its own stages. Never invents: only values present in `normalized_map`
    can come back, and several hits ask instead of guessing.
    """
    for expansion in expansions:
        hits = sorted(
            {
                candidate
                for norm, group in normalized_map.items()
                if expansion in norm
                for candidate in group
            }
        )
        if len(hits) == 1:
            return ResolvedValue(
                field=field_name,
                original_text=original_text,
                normalized_text=normalized_input,
                matched_value=hits[0],
                match_type="alias",
                confidence=0.9,
                grounded=True,
            )
        if len(hits) > 1:
            return ResolvedValue(
                field=field_name,
                original_text=original_text,
                normalized_text=normalized_input,
                matched_value=None,
                match_type="ambiguous",
                confidence=0.6,
                alternatives=_dedupe_preserve_order(hits)[:5],
                grounded=False,
                clarification_required=True,
            )
    return None


def resolve_value(field_name: str, original_text: str, candidates: list[str]) -> ResolvedValue:
    """Pure matcher: `original_text` against a pre-fetched grounded `candidates` list.

    Never fuzzy-matches into an unrestricted guess — a low-confidence or
    multi-way-tied match degrades to `no_match`/`ambiguous`, never a forced
    single answer.
    """
    normalized_input = normalize(original_text)

    if not normalized_input:
        # Punctuation-only / whitespace-only mentions can never ground; without
        # this guard an empty input prefix-matches EVERY candidate below.
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
        normalized_candidate = normalize(candidate)
        if not normalized_candidate:
            # An empty/dirty DB value ('', '  ', ',') must never become a
            # grounded match — an empty norm prefix-matches every input.
            continue
        normalized_map.setdefault(normalized_candidate, []).append(candidate)

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

    # A curated demonym outranks a coincidental prefix collision: "turk"
    # prefix-matches both "Türkiye" and "Türkmenistan", so the generic stage
    # below would ask which one was meant for every "türk hasta" question. The
    # alias states the intent explicitly, and its expansion is still grounded by
    # containment — a demonym whose country is absent from the data returns
    # no_match rather than an invented value. Departments keep the late
    # last-resort placement: their colloquial terms do not prefix-collide, and
    # promoting them would override a legitimate prefix hit.
    if field_name == "nationality" and normalized_input in _NATIONALITY_ALIASES:
        alias_hit = _resolve_by_alias(
            field_name, original_text, normalized_input, normalized_map,
            _NATIONALITY_ALIASES[normalized_input],
        )
        if alias_hit is not None:
            return alias_hit

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

    # Last resort for alias-carrying fields: expand a colloquial term to the
    # wording the real values are built from and look for it INSIDE the grounded
    # values — department names carry qualifiers ("Kulak Burun Boğaz
    # (Ataşehir)") and nationalities are stored as countries ("Türkiye") rather
    # than demonyms ("türk"), both of which defeat prefix and fuzzy matching.
    # Still grounded: only values that actually exist can be returned, and a
    # term matching several different values asks instead of guessing.
    field_aliases = _ALIASES_BY_FIELD.get(field_name)
    if field_aliases is not None:
        alias_hit = _resolve_by_alias(
            field_name, original_text, normalized_input, normalized_map,
            field_aliases.get(normalized_input, ()),
        )
        if alias_hit is not None:
            return alias_hit

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
            if folded_word in _QUESTION_WORDS:
                break
            exception_words = _GENERIC_QUANTIFIER_EXCEPTIONS.get(folded_word)
            is_exception = bool(
                exception_words and phrase_tokens and fold(phrase_tokens[0]) in exception_words
            )
            if not is_exception and _is_dimension_noun(folded_word):
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
            # The walk-back requires a Capitalized proper-noun run, which real
            # department VALUES satisfy ("Kardiyoloji bölümünde", "KBB") but
            # colloquial ones do not ("kalp branşında", "göz polikliniği") — so
            # the phrase was never extracted and the department filter silently
            # disappeared, answering over EVERY department (live UI testing,
            # 2026-07-31). A lowercase token sitting right before the cue word
            # is accepted only when it is a KNOWN alias; `resolve_value` still
            # has to ground it against real values, so nothing is invented.
            if (
                phrase is None
                and field_name == "department"
                and index - 1 >= 0
                and folded_tokens[index - 1].strip(_STRIP_CHARS) in _DEPARTMENT_ALIASES
            ):
                phrase = tokens[index - 1].strip(_STRIP_CHARS)
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
        alias for alias in _GENDER_ALIASES if re.search(rf"\b{re.escape(alias)}\b", folded_question)
    ]
    matched_gender_codes = {_GENDER_ALIASES[alias] for alias in matched_gender_aliases}
    if len(matched_gender_codes) == 1 and (
        any(marker in folded_question for marker in _FILTER_INTENT_MARKERS)
        or _gender_restricts_patient_cohort(folded_question)
    ):
        shortest_alias = min(matched_gender_aliases, key=len)
        results["gender"] = [shortest_alias]

    # Demonyms behave exactly like the gender aliases above: lowercase, no cue
    # word, attached to the patient noun ("türk hasta"), so the proper-noun
    # walk-back cannot see them. Only run when the cue-root scan found nothing —
    # an explicit "Bulgaristan uyruklu" mention is already grounded and must not
    # be overridden. Two different demonyms describe cohorts being compared, not
    # one filter, so only a single match applies.
    if "nationality" not in results:
        hits = [
            alias
            for alias in _NATIONALITY_ALIASES
            if re.search(rf"\b{re.escape(alias)}\w*\b", folded_question)
        ]
        # "türkmen" matches the "turk" alias too, which would resolve to a
        # second, wrong country and disqualify the whole mention. The longest
        # alias is the one actually written, so drop any alias that is merely a
        # prefix of another hit.
        matched_nationalities = [
            alias
            for alias in hits
            if not any(other != alias and other.startswith(alias) for other in hits)
        ]
        matched_countries = {
            _NATIONALITY_ALIASES[alias][0] for alias in matched_nationalities
        }
        if len(matched_countries) == 1 and _restricts_patient_cohort(
            folded_question, matched_nationalities, prefix=True
        ):
            results["nationality"] = [min(matched_nationalities, key=len)]

    return results


# "kadın hasta ORANI" / "erkek hastaların PAYI" ask what SHARE of the population
# a cohort forms — the cohort is the thing being measured, so restricting the
# whole query to it answers a different question (the cohort's own volume, whose
# share is trivially 100%). Adjacency is the discriminator: a share word right
# after the cohort phrase measures the cohort, while an intervening metric
# ("kadın hastaların GELMEME oranı") measures something else about it, which a
# filter renders correctly.
_COHORT_SHARE_WORDS = ("orani", "oran", "payi", "pay", "yuzdesi", "yuzde")


def _restricts_patient_cohort(
    folded_question: str, aliases: Collection[str], *, prefix: bool = False
) -> bool:
    """True when one of `aliases` modifies "hasta" as a genuine cohort filter.

    Plain "Erkek hastaların en çok gittiği ilk 5 bölüm" carries no explicit
    filter marker ("sadece"/"için"), so it used to yield no gender candidate at
    all and the question silently answered over EVERY patient. Attachment to
    the patient noun is filter intent on its own; the share reading above is
    the one exception.

    `prefix` lets an inflected demonym still attach ("türk hastaların" folds to
    "turk hastalarin"); gender aliases stay exact, as they always were.
    """
    tokens = folded_question.split()
    for index, token in enumerate(tokens):
        matched = (
            any(token.startswith(alias) for alias in aliases)
            if prefix
            else token in aliases
        )
        if not matched:
            continue
        following = tokens[index + 1 :][:2]
        if not following or not following[0].startswith("hasta"):
            continue
        if len(following) > 1 and following[1].startswith(_COHORT_SHARE_WORDS):
            return False
        return True
    return False


def _gender_restricts_patient_cohort(folded_question: str) -> bool:
    """True when a gender word modifies "hasta" as a genuine cohort filter."""
    return _restricts_patient_cohort(folded_question, _GENDER_ALIASES)


# The field's own dimension noun may sit between the value and the share word
# ("Bulgaristan UYRUKLU hastaların oranı", "Kardiyoloji BÖLÜMÜNÜN payı"). Like
# "hasta"/"randevu" it names the axis, not a value, so the walk-back steps over
# it. Derived from `_FIELD_CUE_ROOTS` so a new field cannot be forgotten here.
# Key used when the cohort's field is not known from the wording — the caller
# must find it by grounding the mention against each field's real values.
UNRESOLVED_COHORT_FIELD = "*"

_COHORT_CARRIER_ROOTS: tuple[str, ...] = (
    "hasta",
    "randevu",
    *(root for roots in _FIELD_CUE_ROOTS.values() for root in roots),
)


def _is_cohort_carrier(folded_word: str) -> bool:
    """Whether a token names the axis rather than the cohort being measured.

    Uses the same short-root rule as `_is_dimension_noun`: prefix-matching
    "tur" here stepped straight over "Türkiye", so the home country's own share
    was the one nationality that could not be asked for.
    """
    return any(
        folded_word == root
        or (len(root) >= _MIN_PREFIX_ROOT_LENGTH and folded_word.startswith(root))
        for root in _COHORT_CARRIER_ROOTS
    )


def extract_cohort_share_mentions(question: str) -> dict[str, str]:
    """Finds a cohort whose SHARE is being asked for: {field: raw value text}.

    The field key is `UNRESOLVED_COHORT_FIELD` for anything but gender: which column a
    proper noun belongs to is decided by GROUNDING it, not by guessing. An
    earlier version tried the first field in a fixed list, so every named value
    was offered to `department` and "Bulgaristanlı hastaların oranı" silently
    composed nothing.

    The mirror image of `extract_candidate_phrases`. There, a named value
    narrows the query ("kadın hastaların gelmeme oranı" -> WHERE CinsiyetId =
    'K'). Here the value IS the measurement ("kadın hasta oranı" -> what
    percentage of appointments belong to women), so it must become a metric
    predicate instead — filtering to it would make the answer 100% by
    construction.

    Purely a text step, exactly like its sibling: the caller must ground every
    returned mention against real database values before using it, so a
    mis-read never invents a predicate. That grounding is also what absorbs a
    sentence-initial capital ("Gelmeyenlerin payı" walks back into
    "Gelmeyenlerin", which matches no real department and is dropped).
    """
    folded = fold(question)
    tokens = folded.split()
    original_tokens = question.split()
    results: dict[str, str] = {}

    # Two cohorts named together ("kadın VE erkek randevu oranı") describe a
    # breakdown across the dimension, not one cohort's share of the whole.
    multiple_cohorts = (
        len({_GENDER_ALIASES[alias] for alias in _GENDER_ALIASES if alias in tokens}) > 1
    )

    for index, token in enumerate(tokens):
        if not token.startswith(_COHORT_SHARE_WORDS):
            continue
        # Walk back over the cohort phrase. "hasta"/"randevu" are the domain
        # nouns the cohort is expressed in ("kadın HASTA oranı") and carry no
        # value themselves, so they are stepped over rather than stopped on.
        cursor = index - 1
        while cursor >= 0 and _is_cohort_carrier(tokens[cursor]):
            cursor -= 1
        if cursor < 0:
            continue

        if tokens[cursor] in _GENDER_ALIASES:
            if not multiple_cohorts:
                results.setdefault("gender", tokens[cursor])
            continue

        # Any other field: require a proper-noun run, the same evidence
        # `extract_candidate_phrases` requires for a database text value.
        phrase: list[str] = []
        walk = cursor
        while (
            walk >= 0
            and len(phrase) < _MAX_PHRASE_TOKENS
            and walk < len(original_tokens)
            and _is_entity_candidate(
                original_tokens[walk].strip(_STRIP_CHARS), tokens[walk].strip(_STRIP_CHARS)
            )
        ):
            phrase.insert(0, original_tokens[walk].strip(_STRIP_CHARS))
            walk -= 1
        if not phrase:
            continue
        results.setdefault(UNRESOLVED_COHORT_FIELD, " ".join(phrase))

    return results


_NESTED_SHARE_MARKERS = (
    "icindeki",
    "icinde",
    "icerisindeki",
    "icerisinde",
    "arasindaki",
    "arasinda",
    "grubunda",
)


def extract_nested_share_segments(question: str) -> tuple[str, str] | None:
    """Return ``(denominator cohort, measured cohort/condition)``.

    This is deliberately structural rather than vocabulary-specific. It does
    not decide what either side means and it never creates a database
    predicate; the caller must ground both sides. Consequently the same parser
    serves gender, nationality, department, service, status and future fields.

    Only an explicit containment relation with share wording on its right is
    accepted. A temporal phrase such as "2024 içinde" may have the same marker,
    but its left side cannot ground as a cohort and is therefore rejected by
    the caller without a guess.
    """
    folded = fold(question)
    if not any(token.startswith(_COHORT_SHARE_WORDS) for token in folded.split()):
        return None
    for marker in _NESTED_SHARE_MARKERS:
        match = re.search(rf"\b{re.escape(marker)}\b", folded)
        if match is None:
            continue
        # `fold` performs one-character translations, so these offsets also
        # index the original string. Preserve its casing: proper-name grounding
        # intentionally uses capitalization as evidence (Kardiyoloji, Gebze).
        denominator = question[: match.start()].strip(" ,;:-")
        measured = question[match.end() :].strip(" ,;:-")
        if (
            denominator
            and measured
            and any(word.startswith(_COHORT_SHARE_WORDS) for word in fold(measured).split())
        ):
            return denominator, measured
    return None


def extract_gender_mentions(question: str) -> list[str]:
    """Return distinct curated gender aliases, including Turkish suffixes.

    In a three-condition phrase ("kadınların gelmeme oranı") gender is not the
    token adjacent to the share word and is therefore correctly absent from
    `extract_cohort_share_mentions`. It is still an explicit cohort condition.
    This helper reuses the resolver's alias vocabulary instead of duplicating
    gender codes in the composition node.
    """
    tokens = [token.strip(_STRIP_CHARS) for token in fold(question).split()]
    mentions: list[str] = []
    aliases = sorted(_GENDER_ALIASES, key=len, reverse=True)
    for token in tokens:
        for alias in aliases:
            if " " in alias:
                continue
            if token == alias or (
                len(alias) >= 4
                and token.startswith(alias)
                and token[len(alias) :] in {"lar", "lerin", "larin", "in", "i", "a", "da", "dan"}
            ):
                if alias not in mentions:
                    mentions.append(alias)
                break
    return mentions


def extract_filter_only_phrase(question: str) -> str | None:
    """Extracts a terse follow-up value after "sadece/yalniz".

    Used only by callers that already know the retained grouping dimension, so
    this does not guess which database field the value belongs to.
    """
    folded_question = fold(question)
    if not any(marker in folded_question for marker in ("sadece", "yalniz", "yalnizca")):
        return None

    tokens = question.split()
    cleaned = [_APOSTROPHE_SUFFIX.sub("", token).strip(_STRIP_CHARS) for token in tokens]
    folded_tokens = [fold(token) for token in cleaned]
    markers = {"sadece", "yalniz", "yalnizca"}
    for index, folded_token in enumerate(folded_tokens):
        if folded_token not in markers:
            continue
        phrase: list[str] = []
        cursor = index + 1
        while (
            cursor < len(cleaned)
            and len(phrase) < _MAX_PHRASE_TOKENS
            and _is_entity_candidate(cleaned[cursor], folded_tokens[cursor])
        ):
            phrase.append(cleaned[cursor])
            cursor += 1
        if phrase:
            return " ".join(phrase)
    return None


_EXCLUSION_MARKERS = frozenset({"haric", "haricinde", "disinda", "disaridaki"})


def extract_exclusion_phrase(question: str) -> str | None:
    """Extracts a value EXCLUDED with "hariç"/"dışında" ("Kardiyoloji hariç
    bölüm bazında ..."). Returns the capitalized value-phrase run that
    immediately PRECEDES the exclusion marker, or None. The caller grounds it
    against real values, so a mis-read never invents a filter.
    """
    tokens = question.split()
    cleaned = [_APOSTROPHE_SUFFIX.sub("", token).strip(_STRIP_CHARS) for token in tokens]
    folded_tokens = [fold(token) for token in cleaned]
    for index, folded_token in enumerate(folded_tokens):
        if folded_token not in _EXCLUSION_MARKERS:
            continue
        phrase: list[str] = []
        cursor = index - 1
        while (
            cursor >= 0
            and len(phrase) < _MAX_PHRASE_TOKENS
            and _is_entity_candidate(cleaned[cursor], folded_tokens[cursor])
        ):
            phrase.insert(0, cleaned[cursor])
            cursor -= 1
        if phrase:
            return " ".join(phrase)
    return None


# Wording that marks an explicit two-value comparison ("X ile Y'yi
# karşılaştır", "hangisi daha yoğun: X mi Y mi"). Folded substrings.
_COMPARISON_CONTEXT_MARKERS: tuple[str, ...] = (
    "karsilastir",
    "kiyasla",
    "daha",
    "hangisi",
    "hangi",
    "fark",
    "versus",
    " vs ",
)

_APOSTROPHE_SUFFIX = re.compile(r"['’`].*$")

# Separator words that can join two entity mentions in an enumeration
# ("Kardiyoloji, Ortopedi ve Nöroloji"). Folded, matched as exact tokens.
_ENTITY_LIST_SEPARATORS = frozenset({"ve", "ile", "veya"})


def _is_entity_candidate(word: str, folded_word: str) -> bool:
    """True when a token looks like part of a proper-noun value mention."""
    return bool(
        word
        and word[0].isupper()
        and folded_word not in _QUESTION_WORDS
        and not _is_dimension_noun(folded_word)
    )


def extract_comparison_entities(question: str) -> list[str]:
    """Finds a 3-or-more entity comparison enumeration ("Kardiyoloji, Ortopedi
    ve Nöroloji'yi karşılaştır").

    Returns `[]` for anything shorter: the two-entity case stays with
    `extract_comparison_pair`, whose "X ile Y" / "X mi Y mi" anchoring is
    deliberately narrower and already well covered. Pure text step — the
    caller must still ground EVERY returned mention against real DB values,
    and must abandon the whole enumeration if any single one fails. That
    all-or-nothing rule is what keeps this loose comma/"ve" scan safe: a real
    department name that itself contains "ve" ("Kalp ve Damar Cerrahisi")
    can be mis-split here, but the resulting fragments ("Kalp") never ground,
    so the enumeration is silently dropped rather than half-applied.
    """
    folded_question = fold(question)
    # A 3+-value enumeration is a comparison ("... karşılaştır") OR a multi-value
    # FILTER ("Kardiyoloji, Nöroloji ve Ortopedi BÖLÜMLERİNDE toplam randevu").
    # The filter form carries a field cue (bölüm/şube/hizmet...) instead of a
    # comparison verb; accept either. The caller's all-or-nothing grounding
    # keeps this loose gate safe — a spurious enumeration whose fragments don't
    # all ground on one field is dropped whole (#4 ileri filtreler, 2026-07-29).
    _field_cue = any(
        root in folded_question for roots in _FIELD_CUE_ROOTS.values() for root in roots
    )
    if not _field_cue and not any(
        marker in folded_question for marker in _COMPARISON_CONTEXT_MARKERS
    ):
        return []

    raw_tokens = question.split()
    cleaned = [_APOSTROPHE_SUFFIX.sub("", token).strip(_STRIP_CHARS) for token in raw_tokens]
    folded_tokens = [fold(token) for token in cleaned]
    # A trailing comma both ENDS the current mention and continues the chain,
    # so it has to be read before `_STRIP_CHARS` removes it above.
    ends_with_comma = [
        _APOSTROPHE_SUFFIX.sub("", token).rstrip(".;:!?").endswith(",") for token in raw_tokens
    ]

    def _is_candidate(index: int) -> bool:
        return _is_entity_candidate(cleaned[index], folded_tokens[index])

    longest: list[str] = []
    index = 0
    while index < len(cleaned):
        if not _is_candidate(index):
            index += 1
            continue

        phrases: list[str] = []
        cursor = index
        while True:
            run: list[str] = []
            comma_terminated = False
            while cursor < len(cleaned) and len(run) < _MAX_PHRASE_TOKENS and _is_candidate(cursor):
                run.append(cleaned[cursor])
                comma_terminated = ends_with_comma[cursor]
                cursor += 1
                if comma_terminated:
                    break
            if not run:
                break
            phrases.append(" ".join(run))
            if comma_terminated:
                continue
            if cursor < len(cleaned) and folded_tokens[cursor] in _ENTITY_LIST_SEPARATORS:
                cursor += 1
                continue
            break

        if len(phrases) > len(longest):
            longest = phrases
        index = max(cursor, index + 1)

    return longest if len(longest) >= 3 else []


def extract_comparison_pair(question: str) -> tuple[str, str] | None:
    """Finds an explicit "X ile Y" / "X mi Y mi" comparison pair of
    proper-noun-like mentions. Pure text step — the caller must still ground
    BOTH sides against real DB values before using them as filters; an
    ungrounded pair is silently ignored (never a clarification)."""
    folded_question = fold(question)
    if not any(marker in folded_question for marker in _COMPARISON_CONTEXT_MARKERS):
        return None

    tokens = question.split()
    cleaned = [_APOSTROPHE_SUFFIX.sub("", token).strip(_STRIP_CHARS) for token in tokens]
    folded_tokens = [fold(token) for token in cleaned]

    def _is_candidate(index: int) -> bool:
        return _is_entity_candidate(cleaned[index], folded_tokens[index])

    def _phrase_back(end_index: int) -> str | None:
        """Walks backward from end_index, collecting a multi-word proper-noun
        phrase ("Kadın Doğum", "Genel Cerrahi") instead of a single token —
        without this, a two-word entity name is silently truncated to its
        last word only, which then fails to ground and drops the whole
        comparison (2026-07-24, found via live multi-turn testing: "Ortopedi
        ile Kadın Doğum'u karşılaştır" degraded to a plain OR'd department
        filter instead of an entity comparison)."""
        phrase: list[str] = []
        j = end_index
        while j >= 0 and len(phrase) < _MAX_PHRASE_TOKENS and _is_candidate(j):
            phrase.insert(0, cleaned[j])
            j -= 1
        return " ".join(phrase) if phrase else None

    def _phrase_forward(start_index: int) -> str | None:
        """Mirror of `_phrase_back` for the right-hand side of "ile"."""
        phrase: list[str] = []
        j = start_index
        while j < len(cleaned) and len(phrase) < _MAX_PHRASE_TOKENS and _is_candidate(j):
            phrase.append(cleaned[j])
            j += 1
        return " ".join(phrase) if phrase else None

    # Pattern A: "<X...> ile <Y...>"
    for index, folded_token in enumerate(folded_tokens):
        if folded_token == "ile" and 0 < index < len(cleaned) - 1:
            left = _phrase_back(index - 1)
            right = _phrase_forward(index + 1)
            if left and right:
                return left, right

    # Pattern B: "<X...> mi <Y...> mi"
    question_particles = [
        index
        for index, folded_token in enumerate(folded_tokens)
        if folded_token in ("mi", "mu", "mi̇")
    ]
    if len(question_particles) >= 2:
        first, second = question_particles[0], question_particles[1]
        if first > 0 and second > first + 1:
            left = _phrase_back(first - 1)
            right = _phrase_back(second - 1)
            if left and right:
                return left, right

    # Pattern C: "<X...> ve <Y...> bolumlerini ... karsilastir".
    # This is still grounded all-or-nothing by the caller, so real names that
    # contain "ve" are dropped if the split fragments do not both resolve.
    cue_roots = tuple(root for roots in _FIELD_CUE_ROOTS.values() for root in roots)
    for index, folded_token in enumerate(folded_tokens):
        if folded_token != "ve" or index == 0 or index >= len(cleaned) - 2:
            continue
        left = _phrase_back(index - 1)
        right = _phrase_forward(index + 1)
        if not left or not right:
            continue
        after_right = index + 1 + len(right.split())
        if after_right < len(folded_tokens) and any(
            folded_tokens[after_right].startswith(root) for root in cue_roots
        ):
            return left, right

    return None


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
