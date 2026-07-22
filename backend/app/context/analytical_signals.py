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
branch/doctor/service/category/source are tracked both as DIMENSIONS (which
column the user wants to group/filter by) and, since AI-INTELLIGENCE-016, as
FILTER VALUES — but only via `plan.branch_filters`/`plan.resolved_filters`,
which are populated exclusively by `app.planning.value_resolver.ValueResolver`
against real distinct database values (never rewritten free text, never an
ungrounded/ambiguous match). `from_raw_text()` still never populates these
five filter fields — it runs before a QueryPlan (and therefore before value
resolution) exists for the current turn.
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
    "RandevuTipiAdi": "appointment_type",
    "CinsiyetId": "gender",
    "Uyruk": "nationality",
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

def granularity_to_time_grain(granularity: str | None) -> str | None:
    """Public accessor for `_GRANULARITY_TO_TIME_GRAIN` — the single canonical
    QueryPlan.grouping_granularity -> conversational time_grain vocabulary
    mapping, reused by app.services.reporting_service so the RESOLVED,
    already-known-during-planning grain (AI-INTELLIGENCE-018, item 6) never
    has to be silently re-derived or left None in the API response."""
    return _GRANULARITY_TO_TIME_GRAIN.get(granularity) if granularity else None


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
        "service|category|source|appointment_type|gender|nationality|date.",
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
        description="Grounded branch (SubeAdi) values from QueryPlan.branch_filters — "
        "populated only by app.planning.value_resolver.ValueResolver (AI-INTELLIGENCE-016), "
        "never from rewritten free text.",
    )
    doctor_filters: list[str] = Field(
        default_factory=list,
        description="Grounded doctor (GenelRandevuKaynakAdi) values from "
        "QueryPlan.resolved_filters['doctor'], populated only when grounded=True.",
    )
    service_filters: list[str] = Field(
        default_factory=list,
        description="Grounded service (HizmetAdi) values from "
        "QueryPlan.resolved_filters['service'], populated only when grounded=True.",
    )
    category_filters: list[str] = Field(
        default_factory=list,
        description="Grounded category (KategoriAdi) values from "
        "QueryPlan.resolved_filters['category'], populated only when grounded=True.",
    )
    source_filters: list[str] = Field(
        default_factory=list,
        description="Grounded appointment source (GenelRandevuKaynakAdi) values from "
        "QueryPlan.resolved_filters['appointment_source'], populated only when grounded=True.",
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
    planned_names = {
        item.column: item.canonical_name
        for item in plan.planned_dimensions
        if item.canonical_name
    }
    dimensions: list[str] = []
    for column in plan.dimensions:
        dimension = planned_names.get(column) or _COLUMN_TO_DIMENSION.get(column)
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

    def _grounded_values(field_name: str) -> list[str]:
        # AI-INTELLIGENCE-016: only a grounded app.planning.value_resolver
        # match may enter conversational memory — an ambiguous/no_match
        # resolution never sets `resolved.grounded`, so it never reaches here.
        resolved = plan.resolved_filters.get(field_name)
        return list(resolved.values) if resolved and resolved.grounded else []

    return AnalyticalSignals(
        dimensions=dimensions,
        metrics=list(plan.metrics),
        ranking=ranking,
        limit=plan.limit,
        time_grain=time_grain,
        comparison_targets=comparison_targets,
        status_filters=status_filters,
        department_filters=[plan.department_filter] if plan.department_filter else [],
        branch_filters=list(plan.branch_filters),
        doctor_filters=_grounded_values("doctor"),
        service_filters=_grounded_values("service"),
        category_filters=_grounded_values("category"),
        source_filters=_grounded_values("appointment_source"),
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


_DIMENSION_ADD_MARKERS = (
    "ayir",
    "kirilim ekle",
    "bir de",
    "ayrica",
)
_FILTER_ONLY_MARKERS = ("sadece", "sinirla", "sinirlandir", "filtrele")


def _union(left: list, right: list) -> list:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged


def _filter_family(predicate: str) -> str | None:
    """Returns the constrained column for a simple structured predicate."""
    match = re.match(r"\s*\[?([A-Za-z_][A-Za-z0-9_]*)\]?\s*(?:=|LIKE|IN\s*\()", predicate, re.I)
    return match.group(1).lower() if match else None


def _normalize_query_plan(plan: "QueryPlan", raw_question: str) -> "QueryPlan":
    """Canonicalize planner output without deriving conversational context.

    The planner can emit two equivalent date mentions for one Turkish phrase
    and can default a doctor count to the descriptive appointment-source
    column.  Memory must store one exact, schema-backed contract, so these
    representation-only corrections happen before either persistence or merge.
    """
    from app.planning.models import PlannedDimension
    from app.semantics import catalog
    from app.semantics.view_mapping import fold

    updates: dict = {}

    date_filters = []
    seen_dates: set[tuple[str | None, str, str]] = set()
    for date_filter in plan.date_filters:
        key = (date_filter.column, date_filter.start_date, date_filter.end_date)
        if key not in seen_dates:
            seen_dates.add(key)
            date_filters.append(date_filter)
    if date_filters != plan.date_filters:
        updates["date_filters"] = date_filters

    folded = fold(raw_question)
    dimensions = list(plan.dimensions)
    normalized_planned_dimensions = [
        PlannedDimension(
            column=column,
            canonical_name=_resolve_dimension_disambiguating_source(column, folded),
        )
        for column in dimensions
    ]
    if normalized_planned_dimensions != plan.planned_dimensions:
        updates["planned_dimensions"] = normalized_planned_dimensions
    doctor_count = (
        any(token.startswith(("doktor", "hekim")) for token in folded.split())
        and not any(term in folded for term in _SOURCE_ONLY_TERMS)
        and "appointment_count" in plan.metrics
    )
    if doctor_count and "GenelRandevuKaynakAdi" in dimensions:
        dimensions = [
            "DoktorId" if column == "GenelRandevuKaynakAdi" else column
            for column in dimensions
        ]
        dimensions = list(dict.fromkeys(dimensions))
        updates.update(
            dimensions=dimensions,
            projection=[
                "DoktorId" if column == "GenelRandevuKaynakAdi" else column
                for column in plan.projection
            ],
            required_columns=list(
                dict.fromkeys(
                    "DoktorId" if column == "GenelRandevuKaynakAdi" else column
                    for column in plan.required_columns
                )
            ),
            planned_dimensions=[
                PlannedDimension(
                    column=column,
                    canonical_name=column_to_dimension(column),
                )
                for column in dimensions
            ],
        )

    pattern = catalog.match_pattern(folded)
    if pattern in {"top_n", "ranking"}:
        direction = plan.ranking or catalog.ranking_direction(folded)
        if plan.ranking is None:
            updates["ranking"] = direction
        if plan.order is None:
            updates["order"] = direction
    elif pattern == "bottom_n":
        if plan.ranking is None:
            updates["ranking"] = "ASC"
        if plan.order is None:
            updates["order"] = "ASC"
    elif (
        plan.ranking is None
        and dimensions
        and plan.analysis_type == "count"
        and "appointment_count" in plan.metrics
        and "appointment_count" in from_raw_text(raw_question).metrics
    ):
        # Grouped counts have a deterministic, business-useful default order.
        updates["ranking"] = "DESC"
        updates["order"] = "DESC"

    if (
        plan.analysis_type == "ratio"
        and "CinsiyetId" in dimensions
        and "kadin" in folded
        and "erkek" in folded
    ):
        updates["derived_calculations"] = _union(
            plan.derived_calculations,
            ["female_to_male_ratio: CinsiyetId='K' / CinsiyetId='E'"],
        )

    return plan.model_copy(update=updates) if updates else plan


def merge_query_plans(
    *,
    current: "QueryPlan",
    retained: "QueryPlan | None",
    raw_question: str,
    follow_up_detected: bool,
) -> "QueryPlan":
    """Merge the current explicit plan onto the last successful plan.

    QueryPlanner remains the sole producer of both plans. This function only
    applies conversational precedence to their already-structured fields:
    explicit current values win, untouched values inherit on a genuine
    follow-up, and independent questions return the current plan unchanged.
    """
    current = _normalize_query_plan(current, raw_question)
    if not follow_up_detected or retained is None:
        return current

    from app.semantics.view_mapping import fold

    folded = fold(raw_question)
    merged = retained.model_copy(deep=True)
    updates: dict = {
        "question": raw_question,
        "planner_ms": current.planner_ms,
        "matched_examples": list(current.matched_examples or retained.matched_examples),
    }

    # A new explicit date replaces the whole previous date/period contract.
    if current.date_filters:
        updates.update(
            date_filters=list(current.date_filters),
            periods=list(current.periods),
            current_period=current.current_period,
            baseline_period=current.baseline_period,
        )

    current_dimensions = list(current.dimensions)
    if current_dimensions and any(marker in folded for marker in _FILTER_ONLY_MARKERS):
        # "... ile sınırla" names a filter value, not a new GROUP BY.
        current_dimensions = []
    if current_dimensions:
        additive = any(marker in folded for marker in _DIMENSION_ADD_MARKERS)
        dimensions = (
            _union(retained.dimensions, current_dimensions)
            if additive
            else current_dimensions
        )
        updates["dimensions"] = dimensions
        planned_by_column = {
            item.column: item for item in retained.planned_dimensions
        }
        planned_by_column.update(
            {item.column: item for item in current.planned_dimensions}
        )
        updates["planned_dimensions"] = [
            planned_by_column[column]
            for column in dimensions
            if column in planned_by_column
        ]
        updates["projection"] = _union(
            [value for value in retained.projection if value in dimensions],
            [value for value in current.projection if value in dimensions],
        ) or list(dimensions)

    # Planner defaults on a terse ranking/dimension follow-up are not an
    # explicit metric override.  Only raw-text metric evidence may replace the
    # retained calculation (e.g. retain AVG duration for "top 10 departments").
    explicit_current_metrics = from_raw_text(raw_question).metrics
    if current.metrics and explicit_current_metrics:
        from app.context.merge_policy import merge_metrics

        metrics, _ = merge_metrics(
            current_metrics=current.metrics,
            inherited_metrics=retained.metrics,
            follow_up_detected=True,
            folded_question=folded,
        )
        updates["metrics"] = metrics
        updates["planned_metrics"] = [
            item
            for item in _union(retained.planned_metrics, current.planned_metrics)
            if item.metric_id in metrics
        ]
        # A newly stated metric/calculation intent replaces the prior one.
        for field_name in (
            "aggregation",
            "analysis_type",
            "numerator",
            "denominator",
            "question_goal",
            "cohort",
            "minimum_sample_size",
        ):
            value = getattr(current, field_name)
            if value is not None:
                updates[field_name] = value

    if current.ranking is not None:
        updates["ranking"] = current.ranking
    if current.order is not None:
        updates["order"] = current.order
    if current.limit is not None:
        updates["limit"] = current.limit
    if current.analysis_type in {"ranking", "top_n", "bottom_n"} and (
        current.limit is not None or current.ranking is not None
    ):
        updates["analysis_type"] = current.analysis_type
    if current.grouping_granularity is not None:
        updates["grouping_granularity"] = current.grouping_granularity
    if current.comparisons:
        updates["comparisons"] = list(current.comparisons)
    if current.derived_calculations:
        updates["derived_calculations"] = _union(
            retained.derived_calculations, current.derived_calculations
        )

    # Current structured predicates replace only their own column family;
    # unrelated retained predicates survive.
    if current.extra_filters:
        current_families = {
            family for value in current.extra_filters if (family := _filter_family(value))
        }
        inherited_filters = [
            value
            for value in retained.extra_filters
            if _filter_family(value) not in current_families
        ]
        updates["extra_filters"] = _union(inherited_filters, current.extra_filters)

    updates["resolved_filters"] = {
        **retained.resolved_filters,
        **current.resolved_filters,
    }
    if current.branch_filters:
        updates["branch_filters"] = list(current.branch_filters)
    elif current.scope == "all":
        updates["branch_filters"] = []
        updates["scope"] = "all"

    updates["required_columns"] = _union(
        retained.required_columns, current.required_columns
    )
    updates["assumptions"] = _union(retained.assumptions, current.assumptions)
    return merged.model_copy(update=updates)
