"""Deterministic merge policy for typed analytical follow-up signals (Parts 4-6).

Precedence order applied to every field:

    current explicit canonical value
    -> current semantic/planner value      (same source: AnalyticalSignals.from_*)
    -> inherited context                   (only when a genuine follow-up verdict holds)
    -> default (empty/None)

Pure functions only — no I/O, no provider calls, fully unit-testable. The
`follow_up_detected` gate is computed elsewhere (app.context.resolver, using
the existing deterministic pronoun/elliptical/date-only/negation signals) and
passed in here; a full independent question (no genuine follow-up verdict)
therefore never inherits anything, regardless of entity/word overlap — this
is what makes full-question isolation (Part 6) automatic rather than a
separate rule to maintain.
"""

from app.context.analytical_signals import FILTER_FAMILIES, AnalyticalSignals

# Wording markers that force metric REPLACEMENT even when a metric was
# already active in context (folded forms: göre->gore, yerine unchanged).
_METRIC_REPLACE_MARKERS = ("yerine", "gore yap")
# Wording markers that force metric ADDITION (union) instead of the default
# replace-on-new-metric behavior. Bigrams only (never a bare "de"/"da"/"olsun"
# alone) — each of these is common/generic Turkish on its own and would
# false-positive on unrelated independent sentences.
_METRIC_ADD_MARKERS = ("bir de", "ayrica", "de ekle", "da ekle", "de olsun", "da olsun")
_METRIC_ADD_CONJUNCTION = " ve "


def _has_any(folded_question: str, markers: tuple[str, ...]) -> bool:
    return any(marker in folded_question for marker in markers)


def has_strong_followup_marker(folded_question: str) -> bool:
    """True only for an EXPLICIT add/replace marker ('bir de', 'ayrıca',
    'yerine', '... göre yap') — deliberately excludes the bare ' ve '
    conjunction, which is too common in ordinary, fully independent Turkish
    sentences ("... sayısı ve oranı açısından karşılaştır.") to safely imply
    "this is a follow-up" on its own (Part 6: no false-positive inheritance
    from bare membership/wording overlap).

    AI-INTELLIGENCE-018: a fully-worded additive/replacement follow-up
    ("Bir de gerçekleşme oranını ekle.") has too many content tokens to
    qualify as elliptical, but is still unambiguously a follow-up — used by
    `app.context.resolver.ContextResolver` to recognize it as one so the
    dimension/metric merge (and `context_applied`) reflect the real
    inheritance `merge_metrics()` below already performs (via the separate,
    intentionally broader `_METRIC_ADD_CONJUNCTION` check) regardless of the
    `follow_up_detected` gate.
    """
    return _has_any(folded_question, _METRIC_REPLACE_MARKERS) or _has_any(
        folded_question, _METRIC_ADD_MARKERS
    )


def merge_list_field(
    *,
    current_values: list[str],
    inherited_values: list[str],
    follow_up_detected: bool,
) -> tuple[list[str], bool]:
    """Generic replace-if-explicit / inherit-if-followup / else-clear rule.

    Returns (resolved_values, was_removed) — was_removed is True when a
    previously-held inherited value was cleared or replaced this turn.
    """
    if current_values:
        removed = bool(inherited_values) and set(inherited_values) != set(current_values)
        return list(current_values), removed
    if follow_up_detected and inherited_values:
        return list(inherited_values), False
    return [], bool(inherited_values)


def merge_scalar_field(
    *,
    current_value,
    inherited_value,
    follow_up_detected: bool,
):
    """Same rule as `merge_list_field`, for a single scalar (ranking/limit/time_grain)."""
    if current_value is not None:
        removed = inherited_value is not None and inherited_value != current_value
        return current_value, removed
    if follow_up_detected and inherited_value is not None:
        return inherited_value, False
    return None, inherited_value is not None


def merge_metrics(
    *,
    current_metrics: list[str],
    inherited_metrics: list[str],
    follow_up_detected: bool,
    folded_question: str,
) -> tuple[list[str], bool]:
    """Metric-specific merge (Part 5): replace by default on a new metric,
    additive only when the wording explicitly says so ('bir de', 'ayrıca',
    a bare ' ve ' conjunction), explicit 'yerine'/'... göre yap' always forces
    replacement even if an additive marker is also (implausibly) present.
    """
    if current_metrics:
        wants_replace = _has_any(folded_question, _METRIC_REPLACE_MARKERS)
        wants_add = not wants_replace and (
            _has_any(folded_question, _METRIC_ADD_MARKERS)
            or _METRIC_ADD_CONJUNCTION in folded_question
        )
        if wants_add:
            merged = list(inherited_metrics)
            for metric in current_metrics:
                if metric not in merged:
                    merged.append(metric)
            return merged, False
        removed = bool(inherited_metrics) and set(inherited_metrics) != set(current_metrics)
        return list(current_metrics), removed
    if follow_up_detected and inherited_metrics:
        return list(inherited_metrics), False
    return [], bool(inherited_metrics)


def merge_analytical_signals(
    *,
    current: AnalyticalSignals,
    inherited: AnalyticalSignals,
    follow_up_detected: bool,
    folded_question: str,
) -> tuple[AnalyticalSignals, list[str], list[str]]:
    """Merges one turn's explicit signals against inherited context.

    Returns (resolved_signals, explicit_fields, removed_fields).
    """
    explicit_fields: list[str] = []
    removed_fields: list[str] = []

    dimensions, dims_removed = merge_list_field(
        current_values=current.dimensions,
        inherited_values=inherited.dimensions,
        follow_up_detected=follow_up_detected,
    )
    if current.dimensions:
        explicit_fields.append("dimensions")
    if dims_removed:
        removed_fields.append("dimensions")

    metrics, metrics_removed = merge_metrics(
        current_metrics=current.metrics,
        inherited_metrics=inherited.metrics,
        follow_up_detected=follow_up_detected,
        folded_question=folded_question,
    )
    if current.metrics:
        explicit_fields.append("metrics")
    if metrics_removed:
        removed_fields.append("metrics")

    ranking, ranking_removed = merge_scalar_field(
        current_value=current.ranking,
        inherited_value=inherited.ranking,
        follow_up_detected=follow_up_detected,
    )
    if current.ranking:
        explicit_fields.append("ranking")
    if ranking_removed:
        removed_fields.append("ranking")

    limit, limit_removed = merge_scalar_field(
        current_value=current.limit,
        inherited_value=inherited.limit,
        follow_up_detected=follow_up_detected,
    )
    if current.limit is not None:
        explicit_fields.append("limit")
    if limit_removed:
        removed_fields.append("limit")

    time_grain, time_grain_removed = merge_scalar_field(
        current_value=current.time_grain,
        inherited_value=inherited.time_grain,
        follow_up_detected=follow_up_detected,
    )
    if current.time_grain:
        explicit_fields.append("time_grain")
    if time_grain_removed:
        removed_fields.append("time_grain")

    comparison_targets, cmp_removed = merge_list_field(
        current_values=current.comparison_targets,
        inherited_values=inherited.comparison_targets,
        follow_up_detected=follow_up_detected,
    )
    if current.comparison_targets:
        explicit_fields.append("comparison_targets")
    if cmp_removed:
        removed_fields.append("comparison_targets")

    filter_values: dict[str, list[str]] = {}
    for family in FILTER_FAMILIES:
        current_values = getattr(current, family)
        inherited_values = getattr(inherited, family)
        values, removed = merge_list_field(
            current_values=current_values,
            inherited_values=inherited_values,
            follow_up_detected=follow_up_detected,
        )
        filter_values[family] = values
        if current_values:
            explicit_fields.append(family)
        if removed:
            removed_fields.append(family)

    resolved = AnalyticalSignals(
        dimensions=dimensions,
        metrics=metrics,
        ranking=ranking,
        limit=limit,
        time_grain=time_grain,
        comparison_targets=comparison_targets,
        **filter_values,
    )
    return resolved, explicit_fields, removed_fields
