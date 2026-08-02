"""Question→plan coverage: which recognized signals the plan never used.

`PlanComplianceValidator` proves the generated SQL implements every constraint
the PLAN carries. Nothing proved the plan carries every constraint the QUESTION
carries — so a constraint dropped during planning left no trace to check, and
the agent answered a narrower or different question at full confidence
("Erkek hastaların en çok gittiği ilk 5 bölüm" → every patient's top 5
departments; "randevu süresi 30 dakikadan uzun olanların oranı" → the average
duration). This module closes that direction: it reports view columns the
question demonstrably names but the plan uses nowhere.

Deterministic and side-effect free — it only reports. Callers decide what to do
with a non-empty result (log it, lower confidence, escalate to the LLM, or say
out loud which constraint could not be applied).
"""

from __future__ import annotations

from app.database_intelligence.value_catalog import FIELD_COLUMNS
from app.planning.models import QueryPlan
from app.planning.value_resolver import extract_candidate_phrases, extract_comparison_pair
from app.semantics import catalog, view_mapping

# A generic domain noun mentions the subject of practically every question in
# this domain ("kaç HASTA", "RANDEVU sayısı"); its column is a counting target,
# not a constraint the user asked to apply. Flagging it would fire on almost
# every question and drown the real signal.
_GENERIC_SUBJECT_COLUMNS = frozenset({"HastaId", "Id"})

# Columns that are two renderings of ONE entity, so using either satisfies a
# mention of it. Kept as an explicit, tiny set rather than derived from
# `column_intelligence.json`'s `related_columns`: that field also links columns
# the catalog insists are DIFFERENT concepts (GenelRandevuKaynakAdi lists
# RandevuyuVeren, whose own note is "randevuyu veren doktor değildir"), so
# deriving from it would suppress exactly the confusions worth reporting.
#
# Doctor is the only such pair here: the view has no doctor-name column, so
# "doktor" legitimately resolves to the id (unique_doctor_count -> DoktorId) or
# to the source name used for display (GenelRandevuKaynakAdi).
_EQUIVALENT_COLUMNS: dict[str, frozenset[str]] = {
    "DoktorId": frozenset({"GenelRandevuKaynakAdi"}),
    "GenelRandevuKaynakAdi": frozenset({"DoktorId"}),
}


def _consumed_columns(plan: QueryPlan) -> set[str]:
    """Every view column the plan actually puts to work."""
    used: set[str] = set(plan.dimensions) | set(plan.projection) | set(plan.required_columns)
    used |= {date_filter.column for date_filter in plan.date_filters}

    for expression in plan.extra_filters:
        # Filters are rendered SQL fragments ("DATEDIFF(year, DogumTarihi,
        # GETDATE()) > 60"); any view column named inside one is in use.
        for token in expression.replace("(", " ").replace(")", " ").replace(",", " ").split():
            if token[:1].isalpha():
                used.add(token)

    for field_name, resolved in plan.resolved_filters.items():
        column, _tier = FIELD_COLUMNS.get(field_name, (None, None))
        if column and resolved.grounded:
            used.add(column)

    if plan.department_filter or plan.excluded_departments:
        used.add("GenelRandevuBolumAdi")
    if plan.branch_filters:
        used.add("SubeAdi")

    for column in list(used):
        used |= _EQUIVALENT_COLUMNS.get(column, frozenset())
    return used


def _date_term_spans(folded_question: str) -> list[tuple[int, int]]:
    """Token spans of date-semantics wording that already chose the date column.

    Without this, "bugün kaydedilen randevuları listele" reports RandevuyuVeren
    as dropped: "kaydedilen" picks CreatedDate as the date column AND
    stem-matches RandevuyuVeren's "kaydeden" synonym. The word is spoken for.
    """
    entry = view_mapping.get_view_entry()
    spans: list[tuple[int, int]] = []
    for rule in entry.get("date_semantics", {}).get("rules", []):
        for term in rule.get("terms", []):
            span = catalog.phrase_span(folded_question, term)
            if span is not None:
                spans.append(span)
    return spans


def unconsumed_columns(plan: QueryPlan) -> list[str]:
    """View columns the question names but the plan uses nowhere."""
    folded = catalog.fold(plan.question)
    consumed = _consumed_columns(plan)
    date_spans = _date_term_spans(folded)

    unconsumed: list[str] = []
    for column, span in catalog.match_dimension_spans(folded):
        if column in consumed or column in _GENERIC_SUBJECT_COLUMNS:
            continue
        if any(span[0] < end and start < span[1] for start, end in date_spans):
            continue
        unconsumed.append(column)
    return unconsumed


def unbound_value_mentions(plan: QueryPlan) -> list[str]:
    """Named values the question filters on that never became a filter.

    Must run AFTER value resolution: `ResolveFilterValuesNode` records an entry
    in `resolved_filters` for every candidate it tried, so before it runs every
    candidate looks unbound. An entry that exists but is not `grounded` is
    already handled — it raises a clarification — so only a candidate with NO
    entry at all is silently lost ("Kardiyoloji ile Radyoloji arasında ortalama
    süre farkı" answered over every department).
    """
    mentions: list[str] = []
    for field_name, phrases in extract_candidate_phrases(plan.question).items():
        if field_name not in plan.resolved_filters:
            mentions.extend(phrases[:1])

    pair = extract_comparison_pair(plan.question)
    if pair and not (plan.department_filter or plan.branch_filters):
        grounded_any = any(
            resolved.grounded and resolved.values
            for resolved in plan.resolved_filters.values()
        )
        if not grounded_any:
            mentions.extend(pair)
    return _dedupe(mentions)


def ratio_without_ratio_metric(plan: QueryPlan) -> bool:
    """A share/ratio was asked for but the plan computes a plain aggregate.

    "Randevu süresi 30 dakikadan uzun olanların ORANI" planned
    `appointment_duration_average` — the average duration, not the proportion
    over the threshold. The reading is not narrower, it is a different
    question, and the answer carries no sign of the substitution.
    """
    if plan.analysis_type not in {"ratio", "percentage"}:
        return False
    if plan.numerator and plan.denominator:
        return False
    if any(
        calculation.startswith("share_of_total:") for calculation in plan.derived_calculations
    ):
        # A per-group share of the total is a real answer to "…oranı"; the
        # builder renders it as its own `pay_yuzdesi` column rather than as a
        # rate metric, so metric names alone cannot see it.
        return False
    return not any(metric.endswith(("_rate", "_ratio")) for metric in plan.metrics)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    return [v for v in values if not (v in seen or seen.add(v))]


def partial_reading_reasons(plan: QueryPlan) -> list[str]:
    """Every reason this plan is a PARTIAL reading of its question.

    Empty means the plan accounts for everything the deterministic layers could
    recognize — NOT that the question was fully understood: wording no layer
    parses at all ("kadın hasta oranı", where no catalog term matches) leaves
    nothing to report. That blind spot is the LLM's job, not this module's.
    """
    reasons: list[str] = []
    for column in unconsumed_columns(plan):
        reasons.append(f"unconsumed_column:{column}")
    for mention in unbound_value_mentions(plan):
        reasons.append(f"unbound_value:{mention}")
    if ratio_without_ratio_metric(plan):
        reasons.append("ratio_requested_without_ratio_metric")
    return reasons
