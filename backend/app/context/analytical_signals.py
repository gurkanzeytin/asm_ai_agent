"""Typed analytical follow-up signals: dimensions, metrics, filters, ranking,
limit, time grain, and comparison targets.

This module never reimplements NLU. It has exactly two extraction paths, in
strict preference order (see app.context.context_manager and .resolver):

- `from_query_plan()` — the AUTHORITATIVE path. Reads the already-built
  `QueryPlan` (planner + catalog output) after a turn's real pipeline run has
  completed. Every field here already went through deterministic, tested
  catalog matching and schema/value grounding (app.semantics.catalog,
  app.semantics.view_mapping) — this module only reshapes that output into
  the conversational-memory vocabulary.
- `from_raw_text()` — a DETERMINISTIC FALLBACK, used only where no QueryPlan
  exists yet for the current turn (inside `ContextManager.resolve()`, which
  runs *before* the NLU/planning pipeline, to know what the current turn
  explicitly states for precedence purposes). It calls the same catalog
  matchers the real planner uses (`app.semantics.catalog.match_metrics`,
  `.match_dimensions`, `.match_pattern`, `.match_granularity`,
  `.ranking_direction`, `.detect_period_comparison`) and the same status
  vocabulary (`app.semantics.view_mapping.resolve_status_filter`) — never a
  second, independent pattern set.

Value grounding honesty (see module-level NOTE below `AnalyticalSignals`):
branch/doctor/service/category/source are tracked as DIMENSIONS (which
column the user wants to group/filter by) using real schema/catalog
grounding. Tracking them as FILTER VALUES (e.g. "branch = 'Merkez'") is not
implemented because no grounded value list exists anywhere in this codebase
for those five columns (unlike status and department, which do have a
curated canonical vocabulary) — inventing free-text value extraction here
would risk exactly what item 9 forbids: silently trusting an ungrounded
value. Those filter fields exist on the model (schema-complete, forward
compatible) but are populated only when/if a grounded source becomes
available.
"""

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    # Deferred: app.planning imports app.context.extractor at package-init
    # time, so a module-level import here would create an import cycle
    # (app.context.models -> analytical_signals -> app.planning -> ... ->
    # app.context.extractor -> app.context.models). Only needed for typing;
    # from_query_plan() imports the concrete class lazily at call time.
    from app.planning.models import QueryPlan

# Real view columns (see app/resources/view_semantics.json `concepts`) mapped
# to the canonical dimension vocabulary this module exposes. GenelRandevuKaynakAdi
# is documented as serving both "doctor" (default) and generic "source" —
# disambiguated in `from_raw_text()` by which trigger term actually matched,
# since QueryPlan.dimensions only carries the resolved column, not the term.
_COLUMN_TO_DIMENSION: dict[str, str] = {
    "SubeAdi": "branch",
    "GenelRandevuBolumAdi": "department",
    "HizmetAdi": "service",
    "KategoriAdi": "category",
    "GenelRandevuKaynakAdi": "doctor",
    # DoktorId is a second, more specific column for "doktor bazında"/"doktor
    # kırılım" breakdown wording (see app/resources/column_intelligence.json);
    # same conceptual dimension as GenelRandevuKaynakAdi, different column choice.
    "DoktorId": "doctor",
    "RandevuDurumu": "status",
}

# app.semantics.catalog.match_granularity only ever returns hour|day|week|month
# (see app/resources/column_intelligence.json _GRANULARITY_TERMS) plus "year"
# via the planner's date-span fallback heuristic; "quarter" is part of this
# module's canonical vocabulary but is never actually produced today — no
# quarter/çeyrek granularity trigger exists anywhere in the catalogs.
_GRANULARITY_TO_TIME_GRAIN: dict[str, str] = {
    "hour": "day",  # finer-than-day collapses to the coarsest supported grain
    "day": "day",
    "week": "week",
    "month": "month",
    "quarter": "quarter",
    "year": "year",
}

_STATUS_PREDICATE_PATTERN = re.compile(r"RandevuDurumu\s*=\s*N?'([^']+)'", re.IGNORECASE)

# Raw-text disambiguation between "doctor" and generic "source" for the shared
# GenelRandevuKaynakAdi column (see app/resources/column_intelligence.json
# synonyms: "doktor","hekim","uzman" vs "kaynak","kaynağa göre").
_DOCTOR_TERMS = ("doktor", "hekim", "uzman")
_SOURCE_ONLY_TERMS = ("kaynak", "kaynag")


class AnalyticalSignals(BaseModel):
    """Typed analytical follow-up state — dimensions/metrics/filters/etc.

    Every field is an open vocabulary sourced from the metric/column catalogs
    (app/resources/*.json), never a hardcoded enum baked into this module, so
    adding a metric to the catalog never requires a code change here.
    """

    dimensions: list[str] = Field(
        default_factory=list,
        description="Canonical grouping dimensions: branch|doctor|department|status|"
        "service|category|source|date.",
    )
    metrics: list[str] = Field(
        default_factory=list, description="Metric catalog ids (app/resources/metric_catalog.json)."
    )
    ranking: str | None = Field(default=None, description="'top' or 'bottom'.")
    limit: int | None = Field(default=None, description="Explicit row/group limit requested.")
    time_grain: str | None = Field(
        default=None, description="day | week | month | quarter | year."
    )
    comparison_targets: list[str] = Field(
        default_factory=list,
        description="Comparison period descriptors (e.g. 'current_period_vs_previous_period').",
    )
    status_filters: list[str] = Field(
        default_factory=list, description="Canonical RandevuDurumu values (schema-grounded)."
    )
    department_filters: list[str] = Field(
        default_factory=list, description="Canonical department names (schema-grounded)."
    )
    branch_filters: list[str] = Field(
        default_factory=list,
        description="Branch filter values. Not populated by extraction today — no grounded "
        "branch-name value list exists in this codebase (see module docstring).",
    )
    doctor_filters: list[str] = Field(
        default_factory=list,
        description="Doctor filter values. Not populated by extraction today — no grounded "
        "doctor-name value list exists in this codebase (see module docstring).",
    )
    service_filters: list[str] = Field(
        default_factory=list,
        description="Service filter values. Not populated by extraction today (see docstring).",
    )
    category_filters: list[str] = Field(
        default_factory=list,
        description="Category filter values. Not populated by extraction today (see docstring).",
    )
    source_filters: list[str] = Field(
        default_factory=list,
        description="Source filter values. Not populated by extraction today (see docstring).",
    )

    def is_empty(self) -> bool:
        return not (
            self.dimensions
            or self.metrics
            or self.ranking
            or self.limit
            or self.time_grain
            or self.comparison_targets
            or self.status_filters
            or self.department_filters
            or self.branch_filters
            or self.doctor_filters
            or self.service_filters
            or self.category_filters
            or self.source_filters
        )


# Field-family names, used by the merge policy to iterate deterministically
# rather than hardcoding the same list in multiple places.
FILTER_FAMILIES: tuple[str, ...] = (
    "status_filters",
    "department_filters",
    "branch_filters",
    "doctor_filters",
    "service_filters",
    "category_filters",
    "source_filters",
)
SCALAR_FIELDS: tuple[str, ...] = ("ranking", "limit", "time_grain")
LIST_FIELDS: tuple[str, ...] = ("dimensions", "metrics", "comparison_targets", *FILTER_FAMILIES)


def _extract_status_value(predicate: str) -> str | None:
    match = _STATUS_PREDICATE_PATTERN.search(predicate)
    return match.group(1) if match else None


def from_query_plan(plan: "QueryPlan") -> AnalyticalSignals:
    """Authoritative extraction from a fully-built QueryPlan (post-planning)."""
    dimensions: list[str] = []
    for column in plan.dimensions:
        dimension = _COLUMN_TO_DIMENSION.get(column)
        if dimension and dimension not in dimensions:
            dimensions.append(dimension)

    status_filters: list[str] = []
    for predicate in plan.extra_filters:
        value = _extract_status_value(predicate)
        if value and value not in status_filters:
            status_filters.append(value)

    ranking: str | None = None
    if plan.ranking == "DESC":
        ranking = "top"
    elif plan.ranking == "ASC":
        ranking = "bottom"

    time_grain = (
        _GRANULARITY_TO_TIME_GRAIN.get(plan.grouping_granularity)
        if plan.grouping_granularity
        else None
    )

    comparison_targets = list(plan.comparisons)
    if plan.baseline_period and plan.baseline_period not in comparison_targets:
        comparison_targets.append(plan.baseline_period)

    return AnalyticalSignals(
        dimensions=dimensions,
        metrics=list(plan.metrics),
        ranking=ranking,
        limit=plan.limit,
        time_grain=time_grain,
        comparison_targets=comparison_targets,
        status_filters=status_filters,
        department_filters=[plan.department_filter] if plan.department_filter else [],
    )


def _detect_limit(question: str) -> int | None:
    """Reuses QueryAnalyzer's own 'ilk N' / 'son N' / ranking-count regex —
    the single canonical limit-detection algorithm in this codebase — rather
    than re-deriving an independent pattern. Accessed pre-pipeline (before a
    QueryPlan exists yet), so the private helpers are used directly. The
    regex expects lowercased, punctuation-stripped input (QueryAnalyzer's own
    `_normalize_query_text`), not raw diacritic-folded text — `_fold` alone
    preserves case, so skipping this step silently drops sentence-initial
    matches like 'En düşük 5 ...'.
    """
    from app.services.query_analyzer import QueryAnalyzer

    analyzer = QueryAnalyzer()
    normalized = analyzer._normalize_query_text(question)
    limit, _order = analyzer._detect_limit_and_order(normalized)
    return limit


def column_to_dimension(column: str) -> str | None:
    """Public accessor for `_COLUMN_TO_DIMENSION` — the single canonical
    column-to-dimension-vocabulary mapping, reused by app.planning.planner to
    build `QueryPlan.planned_dimensions` without duplicating this table."""
    return _COLUMN_TO_DIMENSION.get(column)


def _resolve_dimension_disambiguating_source(column: str, folded_question: str) -> str | None:
    """Returns the canonical dimension for a matched column, or None when the
    column is outside this module's target vocabulary (branch/doctor/
    department/status/service/category/source) — e.g. `catalog.match_dimensions`
    can also return columns like DogumTarihi/RandevuTipiAdi/CinsiyetId that are
    real, groupable schema dimensions but simply not part of the analytical
    follow-up vocabulary this layer tracks."""
    dimension = _COLUMN_TO_DIMENSION.get(column)
    if dimension is None:
        return None
    if dimension == "doctor":
        mentions_doctor = any(term in folded_question for term in _DOCTOR_TERMS)
        mentions_source_only = any(term in folded_question for term in _SOURCE_ONLY_TERMS)
        if mentions_source_only and not mentions_doctor:
            return "source"
    return dimension


def from_raw_text(question: str, department: str | None = None) -> AnalyticalSignals:
    """Deterministic fallback extraction from raw question text — used only
    where a real QueryPlan for the current turn doesn't exist yet.

    `department` is accepted rather than re-detected: ContextExtractor already
    resolves department deterministically (used elsewhere in the resolver),
    so this stays the single source of department detection.
    """
    from app.semantics import catalog
    from app.semantics.view_mapping import fold, resolve_status_filter

    folded = fold(question)

    dimensions: list[str] = []
    for column in catalog.match_dimensions(folded):
        dimension = _resolve_dimension_disambiguating_source(column, folded)
        if dimension and dimension not in dimensions:
            dimensions.append(dimension)

    metrics = catalog.match_metrics(folded)

    pattern = catalog.match_pattern(folded)
    ranking: str | None = None
    if pattern == "top_n":
        ranking = "top"
    elif pattern == "bottom_n":
        ranking = "bottom"
    elif pattern == "ranking":
        ranking = "bottom" if catalog.ranking_direction(folded) == "ASC" else "top"

    limit = _detect_limit(question)

    granularity = catalog.match_granularity(folded)
    time_grain = _GRANULARITY_TO_TIME_GRAIN.get(granularity) if granularity else None

    comparison_targets = catalog.detect_period_comparison(folded)

    status_predicate = resolve_status_filter(folded)
    status_value = _extract_status_value(status_predicate) if status_predicate else None

    return AnalyticalSignals(
        dimensions=dimensions,
        metrics=metrics,
        ranking=ranking,
        limit=limit,
        time_grain=time_grain,
        comparison_targets=comparison_targets,
        status_filters=[status_value] if status_value else [],
        department_filters=[department] if department else [],
    )
