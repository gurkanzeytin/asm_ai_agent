import logging
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.query_analysis import AmbiguityResult
from app.database_intelligence.value_catalog import FIELD_COLUMNS
from app.planning.coverage import partial_reading_reasons
from app.planning.models import InlineMetric, MetricPredicate, QueryPlan, ResolvedFilterPlan
from app.planning.predicates import extract_measure_threshold, threshold_label
from app.planning.value_resolver import (
    UNRESOLVED_COHORT_FIELD,
    ValueResolver,
    build_clarification_headline,
    build_clarification_message,
    extract_candidate_phrases,
    extract_cohort_share_mentions,
    extract_comparison_entities,
    extract_comparison_pair,
    extract_exclusion_phrase,
    extract_filter_only_phrase,
    fold,
)
from app.semantics import view_mapping
from app.semantics.catalog import detect_measure_request

logger = logging.getLogger(__name__)

# SQL alias for a plan-composed cohort share. One per plan today: a question
# naming two cohorts is a breakdown, which `extract_cohort_share_mentions`
# already declines to read as a share.
_COHORT_SHARE_ALIAS = "cohort_share_rate"

# CinsiyetId stores codes, and the matched phrase reaching the resolver is
# diacritic-folded ("kadin"), so neither side yields presentable Turkish on its
# own. Every other field stores its own display text and needs no map.
_GENDER_DISPLAY_NAMES = {"K": "Kadın", "E": "Erkek", "D": "Diğer"}

# Text fields a bare cohort value may belong to, tried in turn by
# `_field_for_value`. "doctor" is excluded: it shares GenelRandevuKaynakAdi with
# "appointment_source", so every doctor name would ground twice and read as
# ambiguous.
_VALUE_FIELDS = (
    "department",
    "branch",
    "nationality",
    "service",
    "category",
    "appointment_type",
    "appointment_status",
)


def _cohort_display_name(column: str, resolved) -> str:
    """Turkish name for the cohort a composed share is measured over."""
    if column == "CinsiyetId":
        return _GENDER_DISPLAY_NAMES.get(resolved.matched_value, resolved.matched_value)
    return resolved.matched_value


class ResolveFilterValuesNode(IAgentNode):
    """Grounds candidate filter phrases against real DB values (AI-INTELLIGENCE-016).

    Runs after planning, before SQL generation. Never invents a filter — an
    unresolved or ambiguous candidate degrades to a clarification request
    (state.ambiguity) instead of a guessed LIKE predicate. Organization-wide
    scope (plan.scope == "all") never resolves a branch-family filter.

    `state.forced_filter_override` (AI-INTELLIGENCE-017) short-circuits
    extraction/resolution for fields already resolved by a pending
    clarification reply ("hepsini", an explicit candidate, an ordinal) —
    those fields are applied directly, never re-extracted from text, so a
    replayed original question can never re-trigger the same clarification.
    """

    def __init__(self, resolver: ValueResolver | None = None) -> None:
        self.resolver = resolver or ValueResolver()

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("ResolveFilterValuesNode execution started.")
        start_time = time.perf_counter()
        plan = state.query_plan
        ambiguity: AmbiguityResult | None = None

        try:
            if plan is not None:
                plan, ambiguity = await self._resolve_plan(plan, state.forced_filter_override)
        except Exception as error:
            logger.error(
                f"ResolveFilterValuesNode failed; continuing without grounded filters: {error}"
            )

        duration = (time.perf_counter() - start_time) * 1000
        logger.info("ResolveFilterValuesNode completed.")

        return state.model_copy(
            update={
                "query_plan": plan,
                "ambiguity": state.ambiguity or ambiguity,
                "current_node": "resolve_filter_values",
                "completed_nodes": state.completed_nodes + ["resolve_filter_values"],
                "duration_ms": state.duration_ms + duration,
                "node_timings": {**state.node_timings, "resolve_filter_values": duration},
            }
        )

    async def _resolve_plan(
        self, plan: QueryPlan, forced_overrides: dict[str, list[str]]
    ) -> tuple[QueryPlan, AmbiguityResult | None]:
        resolved_filters = dict(plan.resolved_filters)
        branch_filters = list(plan.branch_filters)
        ambiguity: AmbiguityResult | None = None

        # Pending-clarification overrides (a resolved "hepsini"/ordinal/explicit
        # reply) always win and are never re-extracted from text.
        for field_name, values in forced_overrides.items():
            resolved_filters[field_name] = ResolvedFilterPlan(
                field=field_name,
                values=list(values),
                source="pending_clarification",
                confidence=1.0,
                grounded=True,
                match_type="alias" if values else "cleared",
                clarification_required=False,
            )
            if field_name == "branch":
                branch_filters = list(values)

        candidates = extract_candidate_phrases(plan.question)
        short_filter_phrase = extract_filter_only_phrase(plan.question)
        if short_filter_phrase:
            retained_dimension_fields = {
                "GenelRandevuBolumAdi": "department",
                "SubeAdi": "branch",
                "GenelRandevuKaynakAdi": "doctor",
                "DoktorId": "doctor",
                "HizmetAdi": "service",
                "KategoriAdi": "category",
                "RandevuTipiAdi": "appointment_type",
            }
            for dimension in plan.dimensions:
                field_name = retained_dimension_fields.get(dimension)
                if field_name and field_name not in candidates:
                    candidates[field_name] = [short_filter_phrase]
                    break
        if plan.scope == "all":
            # Organization-wide scope: never resolve a branch-family filter,
            # regardless of any capitalized-looking token near the phrase.
            candidates = {field: v for field, v in candidates.items() if field != "branch"}
        candidates = {field: v for field, v in candidates.items() if field not in forced_overrides}

        for field_name, phrases in candidates.items():
            phrase = phrases[0]
            resolved = await self.resolver.resolve(field_name, phrase)
            resolved_filters[field_name] = ResolvedFilterPlan(
                field=field_name,
                values=(
                    [resolved.matched_value] if resolved.grounded and resolved.matched_value else []
                ),
                source="grounded_value_resolver",
                confidence=resolved.confidence,
                grounded=resolved.grounded,
                match_type=resolved.match_type,
                original_text=resolved.original_text,
                clarification_required=resolved.clarification_required,
                clarification_message=(
                    build_clarification_message(resolved)
                    if resolved.clarification_required
                    else None
                ),
                alternatives=resolved.alternatives,
            )

            if field_name == "branch" and resolved.grounded and resolved.matched_value:
                branch_filters = [resolved.matched_value]

            if resolved.clarification_required and ambiguity is None:
                # `question` carries only the lead sentence — GenerateClarificationNode
                # renders `options` as its own bullet list; embedding the bullets
                # here too would render every option twice (item 4).
                ambiguity = AmbiguityResult(
                    matched_phrase=resolved.original_text,
                    question=build_clarification_headline(resolved),
                    options=resolved.alternatives or [],
                )

        # Explicit multi-value comparison ("Kardiyoloji ile Psikiyatri'yi
        # karşılaştır", "Kardiyoloji, Ortopedi ve Nöroloji'yi karşılaştır"):
        # EVERY side must ground on the SAME field; anything less is silently
        # ignored — a guessed set must never trigger a clarification or an
        # invented filter. That all-or-nothing rule is also what makes the
        # looser 3+-entity comma/"ve" scan safe (a real name containing "ve",
        # e.g. "Kalp ve Damar Cerrahisi", can be mis-split there, but the
        # fragments never ground, so the enumeration is dropped whole).
        pair = extract_comparison_pair(plan.question)
        mentions = extract_comparison_entities(plan.question) or (
            list(pair) if pair is not None else []
        )
        if len(mentions) >= 2:
            for field_name in ("department", "branch"):
                if field_name in forced_overrides:
                    continue
                existing = resolved_filters.get(field_name)
                if existing is not None and existing.grounded and len(existing.values) >= 2:
                    continue
                grounded = [
                    await self.resolver.resolve(field_name, mention) for mention in mentions
                ]
                if not all(item.grounded and item.matched_value for item in grounded):
                    continue
                values = list(dict.fromkeys(item.matched_value for item in grounded))
                if len(values) < 2:
                    continue
                resolved_filters[field_name] = ResolvedFilterPlan(
                    field=field_name,
                    values=values,
                    source="grounded_value_resolver",
                    confidence=min(item.confidence for item in grounded),
                    grounded=True,
                    match_type="comparison_pair",
                    original_text=" / ".join(mentions),
                    clarification_required=False,
                )
                if field_name == "branch":
                    branch_filters = values
                # A multi-value enumeration is either a COMPARISON ("X, Y ve Z'yi
                # karşılaştır" -> per-entity breakdown) or a plain multi-value
                # FILTER ("X, Y ve Z bölümlerinde toplam kaç randevu" -> a single
                # containment-OR total, keeping the requested aggregation).
                # Only a real comparison verb switches the plan to the entity
                # comparison path; otherwise the grounded values stay as an
                # ordinary IN/containment filter (#4 ileri filtreler,
                # 2026-07-29).
                wants_comparison = any(
                    marker in fold(plan.question)
                    for marker in ("karsilastir", "kiyasla", " vs ", "versus", "hangisi")
                )
                if wants_comparison:
                    # An entity comparison selects entity labels and counts,
                    # never a raw display column; `projection` must be cleared
                    # alongside `dimensions` or a leftover concept column from
                    # the bare "bölüm" mention fails compliance's projection
                    # check (same failure class as the Phase 10 scalar bug).
                    plan = plan.model_copy(
                        update={
                            "analysis_type": "comparison",
                            "dimensions": [],
                            "planned_dimensions": [],
                            "projection": [],
                        }
                    )
                break

        # Department EXCLUSION ("Kardiyoloji hariç bölüm bazında ..."): ground
        # the excluded name and carry it on the plan so the builder renders an
        # atomic NOT IN / NOT-containment filter (#4 ileri filtreler,
        # 2026-07-29). Grounded all-or-nothing, exactly like the value filters.
        excluded_departments = list(plan.excluded_departments)
        cleared_department_filter = False
        if not excluded_departments and "department" not in forced_overrides:
            exclusion_phrase = extract_exclusion_phrase(plan.question)
            if exclusion_phrase:
                grounded = await self.resolver.resolve("department", exclusion_phrase)
                if grounded.grounded and grounded.matched_value:
                    excluded_departments = [grounded.matched_value]
                    # "Kardiyoloji hariç ..." mis-parses as a positive department
                    # filter during planning (the bare name reads like a value
                    # cue). Drop that positive filter when it names the SAME value
                    # we are excluding, or filter and exclusion cancel to 0 rows.
                    if plan.department_filter in excluded_departments:
                        cleared_department_filter = True
                        resolved_filters.pop("department", None)

        update = {
            "resolved_filters": resolved_filters,
            "branch_filters": branch_filters,
            "excluded_departments": excluded_departments,
        }
        if cleared_department_filter:
            update["department_filter"] = None
        plan = plan.model_copy(update=update)
        plan = await self._apply_cohort_share(plan)
        plan = self._apply_measure_threshold(plan)

        # Question→plan coverage. This node is the last stage that can still add
        # a constraint, so it is the first point where "the plan accounts for
        # everything we recognized" is a meaningful statement. Diagnostic only:
        # recorded and logged, never routed on, until the escalation path that
        # consumes it is built and measured.
        reasons = partial_reading_reasons(plan)
        if reasons:
            logger.warning(
                "Partial reading of the question — the plan does not carry every "
                "recognized constraint: %s",
                "; ".join(reasons),
                extra={"partial_reading_reasons": reasons},
            )
            plan = plan.model_copy(update={"partial_reading_reasons": reasons})
        return plan, ambiguity

    def _apply_measure_threshold(self, plan: QueryPlan) -> QueryPlan:
        """Applies a numeric bound on a measure column ("30 dakikadan uzun").

        Two readings of the same bound, decided by what was asked for:
          - a SHARE ("...oranı") makes it the numerator's predicate, so the
            denominator stays every appointment;
          - anything else ("...sayısı", "...listele") makes it a row filter.

        Whatever number the user wrote is the bound; nothing here is specific to
        a particular value.
        """
        predicate = extract_measure_threshold(plan.question)
        if predicate is None:
            return plan
        if _COHORT_SHARE_ALIAS in plan.metrics:
            return plan

        wants_share = detect_measure_request(fold(plan.question)) == "rate" and not any(
            metric.endswith(("_rate", "_ratio")) for metric in plan.metrics
        )
        if not wants_share:
            rendered = f"{predicate.column} {predicate.operator} {int(predicate.values[0])}"
            if rendered in plan.extra_filters:
                return plan
            return plan.model_copy(update={"extra_filters": [*plan.extra_filters, rendered]})

        logger.info(
            "Composed a threshold share metric: %s %s %s.",
            predicate.column,
            predicate.operator,
            predicate.values[0],
        )
        # A duration AVERAGE is not what "how many of them run over 30 minutes"
        # asks for; it is the metric this share replaces.
        return self._composed_share(
            plan,
            predicate,
            f"{threshold_label(predicate)} oranı",
            drop_prefixes=("appointment_duration",),
        )

    async def _field_for_value(self, mention: str):
        """Which field a bare value name belongs to, decided by grounding it.

        "Bulgaristanlı hastaların oranı" names a nationality, "Kardiyoloji
        randevularının payı" a department, and the wording alone does not say
        which — only the data does. Every text field is tried and EXACTLY ONE
        must ground: a value that exists in two fields is genuinely ambiguous,
        and composing a share over the wrong column would answer confidently
        with the wrong number. Returns (None, None) in that case, leaving the
        coverage check to report the unread request.
        """
        hits = []
        for field_name in _VALUE_FIELDS:
            resolved = await self.resolver.resolve(field_name, mention)
            if resolved.grounded and resolved.matched_value:
                hits.append((field_name, resolved))
        if len(hits) != 1:
            if hits:
                logger.info(
                    "Cohort value %r grounds in %s; too ambiguous to compose a share.",
                    mention,
                    [field for field, _ in hits],
                )
            return None, None
        return hits[0]

    def _composed_share(
        self,
        plan: QueryPlan,
        predicate: MetricPredicate,
        label: str,
        *,
        extra_update: dict | None = None,
        drop_prefixes: tuple[str, ...] = (),
    ) -> QueryPlan:
        """Attaches a plan-composed share metric.

        The single place a composed metric is put on a plan, so the invariants
        that keep a share honest hold on every path into it.
        """
        column = predicate.column
        # INVARIANT 1 — the cohort column carries the share and appears nowhere
        # else. Left as a GROUP BY dimension each row is one cohort value, so
        # the share reads 100% on its own row and 0% on every other; left as a
        # WHERE filter the denominator shrinks to the cohort itself and the
        # share is 100% everywhere. Both are the failure this metric exists to
        # remove, so neither is left to the callers to remember.
        dimensions = [dimension for dimension in plan.dimensions if dimension != column]
        resolved_filters = {
            field: resolved
            for field, resolved in plan.resolved_filters.items()
            if FIELD_COLUMNS.get(field, (None, None))[0] != column
        }
        update: dict = {"dimensions": dimensions, "resolved_filters": resolved_filters}
        if column == "GenelRandevuBolumAdi":
            update["department_filter"] = None
        if column == "SubeAdi":
            update["branch_filters"] = []

        # INVARIANT 2 — one share per answer. `share_of_total` renders a second
        # percentage over whatever the primary metric is; with a composed share
        # leading, that is a percentage OF a percentage (100.0 * 100.0 * ...).
        derived = [
            calculation
            for calculation in plan.derived_calculations
            if not calculation.startswith("share_of_total:")
        ]

        # The share leads: it is what was asked, so it is the metric the answer
        # ranks and headlines. The plain volume follows, because a share cannot
        # be sanity-checked without the base it is a share of ("bölüm bazında
        # toplam randevu sayısı VE kadın oranı" is one question).
        metrics = [
            metric
            for metric in plan.metrics
            if metric not in (_COHORT_SHARE_ALIAS, "appointment_count")
            and not metric.startswith(drop_prefixes or ("\0",))
        ]
        spec = InlineMetric(shape="rate", predicate=predicate, label=label)
        return plan.model_copy(
            update={
                **update,
                **(extra_update or {}),
                "derived_calculations": derived,
                "metrics": [_COHORT_SHARE_ALIAS, *metrics, "appointment_count"],
                "metric_specs": {**plan.metric_specs, _COHORT_SHARE_ALIAS: spec},
                "analysis_type": "ratio",
            }
        )

    async def _apply_cohort_share(self, plan: QueryPlan) -> QueryPlan:
        """Composes a share metric for a cohort the catalog has no rate for.

        "Hangi bölümde kadın hasta oranı en yüksek?" asks what percentage of a
        department's appointments belong to women. The catalog's seven
        `conditional_rate` metrics are one SQL shape with seven hard-coded
        predicates, none of them CinsiyetId, so the question used to degrade to
        a plain appointment count per department — a different answer, given at
        full confidence. Composing the predicate instead answers the whole
        family (gender, nationality, service, category, type) with no metric
        per question.

        A catalog rate always wins: this only fires when none matched.
        """
        if any(metric.endswith(("_rate", "_ratio")) for metric in plan.metrics):
            return plan

        # A named cohort covers a SET of values ("yabancı" = every nationality
        # except the home country), so it is resolved from curated metadata
        # instead of the value resolver, which can only ground one stored value.
        named = view_mapping.named_cohort(fold(plan.question))
        if named and detect_measure_request(fold(plan.question)) == "rate":
            # A named cohort turns a generic natural-language negation into a
            # grounded predicate. The builder must not see the earlier
            # unstructured NEGATION hint after this point; the composed CASE
            # expression below is now the authoritative, deterministic form.
            grounded_extra_filters = [
                extra
                for extra in plan.extra_filters
                if not extra.strip().upper().startswith("NEGATION:")
            ]
            return self._composed_share(
                plan,
                MetricPredicate(
                    column=named["column"], operator=named["operator"], values=[named["value"]]
                ),
                f"{named['label']} oranı",
                extra_update={"extra_filters": grounded_extra_filters},
            )

        mentions = extract_cohort_share_mentions(plan.question)
        if not mentions:
            return plan

        field_name, mention = next(iter(mentions.items()))
        if field_name == UNRESOLVED_COHORT_FIELD:
            field_name, resolved = await self._field_for_value(mention)
            if field_name is None:
                return plan
        else:
            resolved = await self.resolver.resolve(field_name, mention)
        column, _tier = FIELD_COLUMNS.get(field_name, (None, None))
        if column is None:
            return plan
        if not resolved.grounded or not resolved.matched_value:
            # Ungrounded: no predicate is invented. The plan is left as it was
            # and the coverage check below reports the unread share request.
            return plan

        logger.info(
            "Composed a cohort share metric: %s = %s (no catalog rate covers it).",
            _COHORT_SHARE_ALIAS,
            f"{column} = {resolved.matched_value}",
        )
        return self._composed_share(
            plan,
            MetricPredicate(column=column, operator="=", values=[resolved.matched_value]),
            f"{_cohort_display_name(column, resolved)} oranı",
        )
