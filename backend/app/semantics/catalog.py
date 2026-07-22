"""Agent Intelligence catalogs: loading, validation, and deterministic matching.

Single source of truth for column intelligence, metrics, relationships, and
analysis patterns (app/resources/*.json). Catalogs are validated with Pydantic
at first load and cached; an invalid catalog raises a clear configuration error
at startup instead of producing silent wrong plans.
"""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.semantics.view_mapping import fold
from app.shared.exceptions import AppBaseException

logger = logging.getLogger(__name__)

_RESOURCES = Path(__file__).resolve().parent.parent / "resources"


class CatalogValidationError(AppBaseException):
    """Raised when an intelligence catalog file is missing, unreadable, or inconsistent."""

    pass


# ── Pydantic catalog models ──────────────────────────────────────────────────


class ColumnSpec(BaseModel):
    column: str
    business_name: str
    description: str
    data_role: str
    semantic_type: str
    synonyms: list[str] = Field(default_factory=list)
    supported_operations: list[str] = Field(default_factory=list)
    related_columns: list[str] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    pii: bool = False
    selectable: bool = True
    filterable: bool = True
    groupable: bool = False
    aggregatable: str = "none"
    listable_default: bool = False


class UnanswerableConcept(BaseModel):
    terms: list[str]
    reason: str
    alternative: str


class ColumnCatalog(BaseModel):
    view: str
    columns: list[ColumnSpec]
    unanswerable_concepts: list[UnanswerableConcept] = Field(default_factory=list)

    def column_names(self) -> set[str]:
        return {spec.column for spec in self.columns}


class MetricSpec(BaseModel):
    id: str
    name: str
    description: str
    analysis_type: str
    required_columns: list[str]
    formula_type: str
    formula: str | None = None
    plan_description: str | None = None
    status: str | None = None
    status_value: str | None = None
    fixed_dimension: str | None = None
    grouping_granularity: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    compatible_dimensions_group: str | None = None
    compatible_dimensions: list[str] = Field(default_factory=list)
    default_time_column: str = "BaslangicTarihi"
    null_behavior: str = ""
    result_type: str = "integer"


class MetricCatalog(BaseModel):
    view: str
    dimension_groups: dict[str, list[str]] = Field(default_factory=dict)
    status_value_source: str = ""
    metrics: list[MetricSpec]

    def by_id(self) -> dict[str, MetricSpec]:
        return {metric.id: metric for metric in self.metrics}


class RelationshipSpec(BaseModel):
    id: str
    name: str
    columns: list[str]
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    supported_analyses: list[str] = Field(default_factory=list)
    example_questions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RelationshipCatalog(BaseModel):
    view: str
    relationships: list[RelationshipSpec]


class PatternSpec(BaseModel):
    id: str
    triggers: list[str]
    requires: list[str] = Field(default_factory=list)
    dimension_count: list[int] = Field(default_factory=lambda: [0, 1])
    date_behavior: str = "optional_filter"
    ordering: str = "none"
    default_formula: str | None = None
    result_type: str = ""
    example_questions: list[str] = Field(default_factory=list)
    invalid_examples: list[str] = Field(default_factory=list)


class PatternCatalog(BaseModel):
    patterns: list[PatternSpec]


# ── Loading and validation ───────────────────────────────────────────────────


def _read_json(filename: str) -> dict:
    path = _RESOURCES / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise CatalogValidationError(f"Catalog file missing: {path.name}") from e
    except json.JSONDecodeError as e:
        raise CatalogValidationError(f"Catalog file '{path.name}' is not valid JSON: {e}") from e


@lru_cache(maxsize=1)
def load_column_catalog() -> ColumnCatalog:
    catalog = ColumnCatalog(**_read_json("column_intelligence.json"))
    for spec in catalog.columns:
        unknown = set(spec.related_columns) - catalog.column_names()
        if unknown:
            raise CatalogValidationError(
                f"Column '{spec.column}' references unknown related columns: {sorted(unknown)}"
            )
    return catalog


@lru_cache(maxsize=1)
def load_metric_catalog() -> MetricCatalog:
    catalog = MetricCatalog(**_read_json("metric_catalog.json"))
    known_columns = load_column_catalog().column_names()
    seen_ids: set[str] = set()
    for metric in catalog.metrics:
        if metric.id in seen_ids:
            raise CatalogValidationError(f"Duplicate metric id: {metric.id}")
        seen_ids.add(metric.id)
        unknown = set(metric.required_columns) - known_columns
        if unknown:
            raise CatalogValidationError(
                f"Metric '{metric.id}' requires unknown columns: {sorted(unknown)}"
            )
        if metric.compatible_dimensions_group:
            group = catalog.dimension_groups.get(metric.compatible_dimensions_group)
            if group is None:
                raise CatalogValidationError(
                    f"Metric '{metric.id}' references unknown dimension group "
                    f"'{metric.compatible_dimensions_group}'"
                )
            metric.compatible_dimensions = group
        unknown_dims = set(metric.compatible_dimensions) - known_columns
        if unknown_dims:
            raise CatalogValidationError(
                f"Metric '{metric.id}' has unknown compatible dimensions: {sorted(unknown_dims)}"
            )
    return catalog


@lru_cache(maxsize=1)
def load_relationship_catalog() -> RelationshipCatalog:
    catalog = RelationshipCatalog(**_read_json("relationship_catalog.json"))
    known_columns = load_column_catalog().column_names()
    known_metrics = set(load_metric_catalog().by_id())
    for relation in catalog.relationships:
        unknown = (set(relation.columns) | set(relation.dimensions)) - known_columns
        if unknown:
            raise CatalogValidationError(
                f"Relationship '{relation.id}' uses unknown columns: {sorted(unknown)}"
            )
        unknown_metrics = set(relation.metrics) - known_metrics
        if unknown_metrics:
            raise CatalogValidationError(
                f"Relationship '{relation.id}' uses unknown metrics: {sorted(unknown_metrics)}"
            )
    return catalog


@lru_cache(maxsize=1)
def load_pattern_catalog() -> PatternCatalog:
    catalog = PatternCatalog(**_read_json("analysis_patterns.json"))
    seen: set[str] = set()
    for pattern in catalog.patterns:
        if pattern.id in seen:
            raise CatalogValidationError(f"Duplicate analysis pattern id: {pattern.id}")
        seen.add(pattern.id)
    return catalog


def validate_all_catalogs() -> None:
    """Loads every catalog, raising CatalogValidationError on any inconsistency."""
    load_column_catalog()
    load_metric_catalog()
    load_relationship_catalog()
    load_pattern_catalog()


# ── Deterministic matching ───────────────────────────────────────────────────

# Specific analysis patterns must win over generic ones (count is the fallback).
_PATTERN_PRIORITY = [
    # AI-INTELLIGENCE-008: implicit analytical intents beat keyword patterns.
    "anomaly_comparison",
    "cohort_analysis",
    "multi_metric_performance",
    "baseline_comparison",
    "variance_analysis",
    "distribution_inequality",
    "adaptive_time_comparison",
    "percentage_change",
    "period_comparison",
    "conversion",
    "ratio",
    "percentage",
    "lead_time_analysis",
    "repeat_behavior",
    "data_quality",
    "anomaly_candidate",
    "duration_analysis",
    "time_trend",
    "cross_analysis",
    "top_n",
    "bottom_n",
    "ranking",
    "distribution",
    "distinct_count",
    "average",
    "minimum",
    "maximum",
    "count",
]

# Explicit previous-period wording (a single detected date range still implies
# a comparison against the period before it).
_PREVIOUS_PERIOD_PHRASES = (
    "gecen aya gore",
    "onceki aya gore",
    "gecen haftaya gore",
    "onceki haftaya gore",
    "gecen yila gore",
    "onceki yila gore",
    "onceki doneme gore",
)

_ASC_MARKERS = ("en dusuk", "en az", "en seyrek", "en alttaki", "en kisa")

_GRANULARITY_TERMS = [
    ("hour", ("saatlik", "saat bazinda", "saatlere gore")),
    ("day", ("gunluk", "gun bazinda", "gunlere gore", "gun gun", "gune gore")),
    ("week", ("haftalik", "hafta bazinda", "haftalara gore", "haftaya gore dagilim")),
    ("month", ("aylik", "ay bazinda", "aylara gore", "aydan aya")),
]

_AGE_GROUP_TERMS = ("yas grubu", "yas gruplarina", "yas dagilimi", "yaslara gore", "yas araligi")

AGE_GROUP_DERIVATION = (
    "age_group = (DATEDIFF(year, DogumTarihi, GETDATE()) / 10) * 10 (10'luk yaş grupları)"
)


# Light Turkish inflectional suffix stripper (after diacritic folding). Both the
# question and catalog terms are stemmed the same way, so 'iptal oranı' matches
# 'iptal oranları' and 'doktor adı' matches 'doktorların adları'. This is a
# comparison normalizer, not a linguistic stemmer: it only needs to be symmetric.
_TR_SUFFIXES = sorted(
    (
        "larindan", "lerinden", "larinda", "lerinde", "larina", "lerine",
        "larini", "lerini", "larin", "lerin", "lardan", "lerden",
        "larda", "lerde", "lara", "lere", "lari", "leri", "lar", "ler",
        "sindan", "sundan", "sinde", "sunda", "sina", "suna", "sini", "sunu",
        "sinin", "sunun", "si", "su",
        "inden", "undan", "inde", "unda", "inin", "unun", "ini", "unu",
        "ine", "una", "in", "un", "den", "dan", "de", "da", "e", "a", "i", "u",
    ),
    key=len,
    reverse=True,
)

_TOKEN_PATTERN = re.compile(r"\w+")

# Very short words ("tani", "adet") lose their identity when a vowel is stripped
# ("tani" -> "tan" would collide with "tane"); keep them whole.
_MIN_STEM_SOURCE = 5


def _stem(token: str) -> str:
    if len(token) < _MIN_STEM_SOURCE:
        return token
    for suffix in _TR_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)]
    return token


def stem_text(text: str) -> str:
    """Folds and stems every token; used symmetrically on questions and terms."""
    return " ".join(_stem(token) for token in _TOKEN_PATTERN.findall(fold(text)))


def _match_token(question_token: str, term_token: str, allow_prefix: bool) -> bool:
    if question_token == term_token:
        return True
    question_stem, term_stem = _stem(question_token), _stem(term_token)
    if question_stem == term_stem:
        return True
    # Turkish final-k softening before a vowel suffix: ``uyruk`` ->
    # ``uyruğu`` (folded/stemmed as ``uyrug``).  Applying this to both
    # operands keeps the catalog synonym vocabulary authoritative instead of
    # requiring every inflected spelling to be duplicated in resource files.
    if (
        len(question_stem) >= 4
        and len(term_stem) >= 4
        and question_stem[:-1] == term_stem[:-1]
        and {question_stem[-1], term_stem[-1]} == {"g", "k"}
    ):
        return True
    return allow_prefix and len(term_stem) >= 4 and question_stem.startswith(term_stem)


def _phrase_position(folded_question: str, term: str, allow_prefix: bool = True) -> int:
    """Token index of the term phrase in the question (-1 if absent).

    Whole-token matching only: every term token must match a consecutive question
    token (exact, stem-equal, or stem-prefix). Substring matches inside words
    ('top' in 'toplam') never count.
    """
    question_tokens = _TOKEN_PATTERN.findall(folded_question)
    term_tokens = _TOKEN_PATTERN.findall(fold(term))
    if not term_tokens or len(term_tokens) > len(question_tokens):
        return -1
    for start in range(len(question_tokens) - len(term_tokens) + 1):
        if all(
            _match_token(question_tokens[start + offset], term_token, allow_prefix)
            for offset, term_token in enumerate(term_tokens)
        ):
            return start
    return -1


def _term_in(folded_question: str, term: str, allow_prefix: bool = True) -> bool:
    return _phrase_position(folded_question, term, allow_prefix) >= 0


def _phrase_span(
    folded_question: str, term: str, allow_prefix: bool = True
) -> tuple[int, int] | None:
    """Token span (start, end) of the term phrase in the question, or None if absent."""
    start = _phrase_position(folded_question, term, allow_prefix)
    if start < 0:
        return None
    term_tokens = _TOKEN_PATTERN.findall(fold(term))
    return start, start + len(term_tokens)


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def match_metrics(folded_question: str) -> list[str]:
    """Returns metric ids whose synonyms appear in the question, most specific first.

    Conditional (status-based) counts suppress the generic appointment_count when
    both match the SAME mention (e.g. 'gerçekleşen randevuların sayısı' resolves to
    the status metric), but not when the question independently asks for both the
    plain count and a rate as two separate, non-overlapping mentions (e.g. 'randevu
    sayısı ve gerçekleşme oranı') — in that case both must survive.
    """
    catalog = load_metric_catalog()
    scored: list[tuple[int, str]] = []
    spans: dict[str, tuple[int, int]] = {}
    for metric in catalog.metrics:
        best = 0
        best_span: tuple[int, int] | None = None
        for synonym in metric.synonyms:
            span = _phrase_span(folded_question, synonym)
            if span is not None:
                length = len(stem_text(synonym))
                if length > best:
                    best = length
                    best_span = span
        if best:
            scored.append((best, metric.id))
            spans[metric.id] = best_span
    scored.sort(key=lambda item: (-item[0], item[1]))
    matched = [metric_id for _, metric_id in scored]

    by_id = catalog.by_id()
    conditional_spans = [
        spans[mid]
        for mid in matched
        if by_id[mid].formula_type in ("conditional_count", "conditional_rate")
    ]
    if (
        "appointment_count" in matched
        and "appointment_count" in spans
        and any(_spans_overlap(spans["appointment_count"], span) for span in conditional_spans)
    ):
        matched.remove("appointment_count")
    # A matched rate implies its count sibling only when they share the same mention.
    rate_bases: set[str] = set()
    for mid in matched:
        if by_id[mid].formula_type != "conditional_rate":
            continue
        base = by_id[mid].numerator
        if base in matched and base in spans and _spans_overlap(spans[base], spans[mid]):
            rate_bases.add(base)
    matched = [mid for mid in matched if mid not in rate_bases]

    # Fixed-dimension "per X" count variants (appointments_per_branch,
    # appointments_per_doctor, ...) are the same COUNT(*) measure as
    # appointment_count — they exist only so a bare "X bazında sayı" question
    # with no independently-detected dimension still gets one implied via
    # `fixed_dimension`. When appointment_count is ALSO matched (the grouping
    # dimension is independently resolved via match_dimensions), the variant
    # is fully redundant: the same measure would otherwise be emitted twice
    # as two separate COUNT(*) SELECT expressions. Keep only the canonical,
    # dimension-agnostic appointment_count.
    if "appointment_count" in matched:
        matched = [
            mid
            for mid in matched
            if mid == "appointment_count"
            or not (
                by_id[mid].formula_type == "count_rows_grouped"
                and by_id[mid].formula == "COUNT(*)"
            )
        ]
    return matched


def match_dimensions(folded_question: str) -> list[str]:
    """Returns groupable, non-PII, non-time columns whose synonyms appear in the question."""
    catalog = load_column_catalog()
    scored: list[tuple[int, int, str]] = []
    for spec in catalog.columns:
        if not spec.groupable or spec.pii or spec.data_role == "time_dimension":
            continue
        best_len, best_pos, best_tokens = 0, -1, 0
        for synonym in spec.synonyms:
            stemmed_term = stem_text(synonym)
            if stemmed_term and len(stemmed_term) > best_len:
                position = _phrase_position(folded_question, synonym)
                if position >= 0:
                    best_len, best_pos = len(stemmed_term), position
                    best_tokens = len(stemmed_term.split())
        if best_len:
            scored.append((best_len, best_pos, best_tokens, spec.column))
    scored.sort(key=lambda item: (-item[0], item[1]))

    # Overlapping matches at the same token span keep only the most specific column
    # ('doktor bazında' -> DoktorId beats the shorter 'doktor' -> Kaynak).
    selected: list[str] = []
    taken_positions: list[tuple[int, int]] = []
    for _, position, token_count, column in scored:
        span = (position, position + token_count)
        if any(span[0] < end and start < span[1] for start, end in taken_positions):
            continue
        taken_positions.append(span)
        selected.append(column)
    return selected


def match_pattern(folded_question: str, detected_date_ranges: int = 0) -> str | None:
    """Resolves the analysis pattern; specific patterns win over generic ones.

    Trigger matching never uses stem-prefix expansion ('seyri' must not match
    'seyrek'); 'ilk' only signals top_n when followed by a number ('ilk 5'),
    never in temporal wording ('ilk haftasında').
    """
    patterns = {pattern.id: pattern for pattern in load_pattern_catalog().patterns}
    has_previous_phrase = any(phrase in folded_question for phrase in _PREVIOUS_PERIOD_PHRASES)
    for pattern_id in _PATTERN_PRIORITY:
        pattern = patterns.get(pattern_id)
        if pattern is None:
            continue
        if pattern_id in ("period_comparison", "percentage_change"):
            # Comparing periods needs a genuine two-period signal, not just 'karşılaştır'.
            change_triggers = [t for t in pattern.triggers if t not in ("karsilastir", "kiyasla")]
            triggered = any(_term_in(folded_question, t, False) for t in change_triggers)
            generic_compare = any(
                _term_in(folded_question, t, False) for t in ("karsilastir", "kiyasla")
            )
            two_period_signal = has_previous_phrase or detected_date_ranges >= 2
            if triggered or (generic_compare and two_period_signal):
                if has_previous_phrase or detected_date_ranges >= 2 or triggered:
                    if pattern_id == "percentage_change" and not any(
                        _term_in(folded_question, t, False) for t in pattern.triggers
                    ):
                        continue
                    return pattern_id
            continue
        triggers = pattern.triggers
        if pattern_id == "top_n":
            triggers = [t for t in triggers if t != "ilk"]
            if re.search(r"\bilk\s+\d+\b", folded_question):
                return pattern_id
        if any(_term_in(folded_question, trigger, False) for trigger in triggers):
            return pattern_id
    return None


def ranking_direction(folded_question: str) -> str:
    return "ASC" if any(marker in folded_question for marker in _ASC_MARKERS) else "DESC"


def match_granularity(folded_question: str) -> str | None:
    for granularity, terms in _GRANULARITY_TERMS:
        if any(term in folded_question for term in terms):
            return granularity
    return None


def detect_period_comparison(folded_question: str, detected_date_ranges: int = 0) -> list[str]:
    """Returns comparison descriptors when the question compares two periods."""
    if any(phrase in folded_question for phrase in _PREVIOUS_PERIOD_PHRASES):
        return ["current_period_vs_previous_period"]
    if detected_date_ranges >= 2 and any(
        term in folded_question for term in ("karsilastir", "kiyasla", " ile ", "arasindaki fark")
    ):
        return ["two_explicit_periods"]
    return []


def detect_age_group_request(folded_question: str) -> bool:
    return any(term in folded_question for term in _AGE_GROUP_TERMS)


def check_answerability(folded_question: str) -> tuple[bool, str | None, str | None]:
    """Checks the question against concepts known to be absent from the view."""
    for concept in load_column_catalog().unanswerable_concepts:
        for term in concept.terms:
            # Prefix matching is disabled here: refusing to answer must never
            # rest on a loose match ('tutar' must not match 'tutarsız').
            if _term_in(folded_question, term, allow_prefix=False):
                return False, concept.reason, concept.alternative
    return True, None, None


def metric_formula_lines(metric_ids: list[str]) -> list[str]:
    """Compact formula lines for the SQL prompt (only verified formulas)."""
    by_id = load_metric_catalog().by_id()
    lines = []
    for metric_id in metric_ids:
        metric = by_id.get(metric_id)
        if metric is None or metric.status == "requires_verified_mapping":
            continue
        if metric.formula:
            lines.append(f"- {metric.id} ({metric.name}): {metric.formula}")
        elif metric.plan_description:
            lines.append(f"- {metric.id} ({metric.name}): {metric.plan_description}")
    return lines


def required_columns_for(metric_ids: list[str], dimensions: list[str]) -> list[str]:
    by_id = load_metric_catalog().by_id()
    required: list[str] = []
    for metric_id in metric_ids:
        metric = by_id.get(metric_id)
        if metric:
            for column in metric.required_columns:
                if column not in required:
                    required.append(column)
    for column in dimensions:
        if column not in required:
            required.append(column)
    return required
