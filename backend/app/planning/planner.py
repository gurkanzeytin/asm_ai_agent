import logging
import re
import time
from collections import deque
from datetime import timedelta
from typing import TYPE_CHECKING

from app.application_models.query_analysis import QueryAnalysis
from app.context.extractor import ContextExtractor
from app.planning.models import (
    DateFilterPlan,
    JoinStep,
    PeriodPlan,
    PlannedDimension,
    PlannedMetric,
    QueryPlan,
)
from app.semantics import catalog, examples, reasoning, view_mapping

if TYPE_CHECKING:  # avoid importing the database_intelligence package at runtime
    from app.database_intelligence.models import TableMetadata, ViewMetadata
    from app.semantics.models import SemanticFrame

logger = logging.getLogger(__name__)

# Canonical entity type -> backing table in the hospital schema.
_ENTITY_TABLES = {
    "Doctor": "doktorlar",
    "Patient": "hastalar",
    "Appointment": "randevular",
    "Department": "bolumler",
    "Prescription": "receteler",
    "Diagnosis": "tanilar",
    "Invoice": "faturalar",
    "LaboratoryTest": "laboratuvar_testleri",
    "Hospitalization": "yatislar",
}

_DEPARTMENT_TABLE = "bolumler"

# "en yoğun X" means volume of appointments in this domain — when no fact
# entity is mentioned explicitly, appointment volume is the implied fact.
_VOLUME_RANKING_MARKERS = ("yogun", "en cok randevu", "en fazla randevu")

# Generic superlative wording ("en yüksek 10 bölüm") — a ranking request, never
# a raw record list, even though it carries both an order and a limit.
_GENERIC_RANKING_MARKERS = ("en yuksek", "en iyi", "en kotu", "en basarili")

# Distinct-count metrics whose counted concept can ALSO match a grouping
# dimension from the same bare noun (both DoktorId and the descriptive source
# column mean "doctor"). Used to drop the self-referential dimension on pure
# "kaç X var" questions.
_SELF_COUNT_DIMENSIONS: dict[str, set[str]] = {
    "unique_doctor_count": {"GenelRandevuKaynakAdi", "DoktorId"},
    "unique_patient_count": {"HastaId"},
}

_NEGATION_PATTERN = re.compile(r"\b(olmayan|bulunmayan|almayan)\w*\b|\bhic\b")

# Generic organization-wide scope phrases ("tüm aile sağlığı merkezleri", "bütün
# şubeler", "kurum genelinde", ...). These NEVER name a real branch value —
# they mean "no branch filter, every record in scope" — and must never be
# treated as a literal SubeAdi value (see AI-INTELLIGENCE-015 / PlanComplianceValidator).
# "tum"/"butun" + an organizational noun (merkez/sube/hastane), anywhere within
# a short span, or the standalone "genelinde"/"kurum genelinde" wording.
_GENERIC_SCOPE_ALL_PATTERN = re.compile(
    r"\b(?:tum|butun)\b(?:\s+\w+){0,4}?\s+(?:merkez\w*|sube\w*|hastane\w*|lokasyon\w*)\b"
    r"|\b(?:merkez\w*|sube\w*|hastane\w*|lokasyon\w*)(?:\s+\w+){0,4}?\s+(?:tum\w*|butun\w*)\b"
    r"|\bkurum\s+genelinde\b"
    r"|\bgenelinde\b"
)

# "X bazında / X'e göre" grouping wording: the word before the marker names the dimension.
_GROUP_BY_PATTERN = re.compile(r"(\w+)\s+(?:baz(?:inda|li)\b|gore\b)")

_ASCENDING_MARKERS = ("en az", "en dusuk", "en seyrek")

_DESCRIPTIVE_PRIORITY = ("ad_soyad", "bolum_adi", "sirket_adi", "test_adi", "name", "title")

_PERIOD_ANALYSIS_TYPES = {
    "period_comparison",
    "baseline_comparison",
    "adaptive_time_comparison",
    "percentage_change",
}

_MONTH_LABELS = (
    "",
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)


class QueryPlanner:
    """Deterministic planner organizing NLU output into a QueryPlan (AG-022).

    Only arranges information already extracted by the NLU and the schema
    retriever — it never generates SQL and never calls an LLM.
    """

    def __init__(self, context_extractor: ContextExtractor | None = None) -> None:
        self._extractor = context_extractor or ContextExtractor()

    def build_plan(
        self,
        question: str,
        analysis: QueryAnalysis,
        tables: list["TableMetadata"],
        semantic_frame: "SemanticFrame | None" = None,
        views: "list[ViewMetadata] | None" = None,
    ) -> QueryPlan:
        start = time.perf_counter()
        folded = self._extractor.fold(question)
        signals = self._extractor.extract(question)
        table_map = {table.name: table for table in tables}
        generic_scope_phrase = self._detect_generic_scope(folded)
        scope = "all" if generic_scope_phrase else "filtered"
        scope_assumptions = (
            ["Genel kapsam: belirli bir şube filtresi uygulanmadı (tüm şubeler dahil)."]
            if generic_scope_phrase
            else []
        )

        # REASONING-001: when a semantic frame is provided it is the
        # authoritative interpretation — the planner organizes, it does not
        # re-derive what the user meant.
        if semantic_frame is not None and semantic_frame.primary_subject:
            output_entity = semantic_frame.primary_subject
            fact_entity = semantic_frame.fact_subject or output_entity
        else:
            output_entity, fact_entity = self._entities(analysis, folded)
        output_table = self._entity_table(output_entity, table_map)
        fact_table = self._entity_table(fact_entity, table_map) or output_table

        date_filters = self._date_filters(analysis, fact_table or output_table, table_map)
        aggregation = self._aggregation(analysis)
        ranking, order = self._ranking(analysis, signals.analysis_type, folded)
        extra_filters = self._extra_filters(folded)
        raw_list_request = self._raw_list_request(analysis, folded)

        join_path = self._join_path(
            fact_table,
            output_table,
            signals.department,
            table_map,
        )
        # Pure aggregate questions over a single entity ("Bugün kaç randevu?")
        # return a scalar — requiring a descriptive projection would be wrong.
        if aggregation and (output_table == fact_table or output_table is None):
            projection: list[str] = []
        else:
            projection = self._projection(output_table, table_map)
        distinct = bool(
            output_table and fact_table and output_table != fact_table and not aggregation
        )

        # Single-view deployments (SQL Server dbo.vw_RandevuRaporu): resolve the
        # user's business concepts to real view columns using the central semantic
        # metadata (resources/view_semantics.json). No joins exist in this world.
        if views and not table_map:
            view_name = views[0].name
            output_entity = self._view_output_entity(analysis, output_entity)
            output_table = view_name
            fact_table = view_name
            join_path = []
            distinct = False

            date_column = view_mapping.resolve_date_column(folded, view_name)
            if date_column:
                date_filters = [
                    date_filter.model_copy(update={"column": date_column})
                    for date_filter in date_filters
                ]

            measure = view_mapping.resolve_measure(folded, view_name)
            if measure:
                aggregation = measure

            concept_column = view_mapping.concept_column(output_entity or "", view_name)
            if ranking and not concept_column:
                # "En yoğun 5 bölümü göster": the ranked dimension is the first
                # detected entity that maps to a descriptive view column.
                for entity in analysis.entities:
                    candidate = view_mapping.concept_column(entity.entity_type, view_name)
                    if candidate and not candidate.lower().endswith("id"):
                        concept_column = candidate
                        output_entity = entity.entity_type
                        break

            group_column = self._view_group_dimension(folded, view_name)
            if group_column:
                projection = [group_column]
                if not aggregation:
                    aggregation = "COUNT(*)"
            elif concept_column and not concept_column.lower().endswith("id"):
                # Id-like concept columns (HastaId) are for counting, never for
                # default projection: identity/contact fields stay unselected.
                projection = [concept_column]
            else:
                projection = []

            if ranking and not aggregation and "randevu" in folded:
                # Ranked dimensions are ranked by appointment volume in this domain.
                aggregation = "COUNT(*)"

            status_filter = view_mapping.resolve_status_filter(folded, view_name)
            if status_filter:
                extra_filters = extra_filters + [status_filter]
            status_value = view_mapping.resolve_status_value(folded, view_name)

            # Status negation ("gerçekleşmeyenler", "tamamlanmayan"): renders as
            # an IN-list over the complement statuses — the SAME equality/IN
            # rendering path already used for a positive status filter, never a
            # new '<>' predicate. Mutually exclusive with the positive match
            # above (a question naming both would be contradictory).
            if not status_filter:
                negated_status_values = view_mapping.resolve_negated_status_values(
                    folded, view_name
                )
                if negated_status_values:
                    negated_column = view_mapping.status_column(view_name)
                    extra_filters = extra_filters + [
                        f"{negated_column} = '{value}'" for value in negated_status_values
                    ]

            intelligence = self._resolve_intelligence(
                folded, analysis, projection, aggregation, ranking, status_value
            )
            if raw_list_request:
                list_projection = self._view_list_projection(view_name)
                intelligence.update(
                    {
                        "metrics": [],
                        "dimensions": [],
                        "analysis_type": "list",
                        "aggregation": None,
                        "projection": list_projection,
                        "numerator": None,
                        "denominator": None,
                        "granularity": None,
                        "comparisons": [],
                        "derived": [],
                        "required_columns": list_projection,
                    }
                )
                aggregation = None
            # A conditional-rate metric embeds the status condition in its own
            # numerator; a hard status WHERE filter would corrupt the denominator.
            if intelligence["numerator"] and status_filter:
                extra_filters = [f for f in extra_filters if f != status_filter]

            # AI-INTELLIGENCE-008: implicit analytical wording resolves to an
            # explicit strategy (goal, cohort, baseline, KPI set, assumptions).
            strategy = None
            if intelligence["answerable"]:
                strategy = reasoning.resolve_strategy(
                    folded, intelligence["metrics"], intelligence["dimensions"]
                )
            if strategy is not None:
                intelligence["analysis_type"] = strategy.analysis_type
                merged_metrics = list(strategy.metrics)
                for metric_id in intelligence["metrics"]:
                    if metric_id not in merged_metrics:
                        merged_metrics.append(metric_id)
                intelligence["metrics"] = merged_metrics
                if strategy.dimensions:
                    intelligence["dimensions"] = strategy.dimensions
                if strategy.baseline_period and not intelligence["comparisons"]:
                    intelligence["comparisons"] = [
                        f"{strategy.current_period or 'current'}_vs_{strategy.baseline_period}"
                    ]
                if strategy.cohort:
                    intelligence["derived"] = intelligence["derived"] + [
                        f"cohort: {strategy.cohort}"
                    ]
                if strategy.comparison_direction == "no_increase":
                    # Inverted follow-up predicate: groups WITHOUT an increase.
                    ranking = "ASC"
                    order = "ASC"
                    intelligence["derived"] = intelligence["derived"] + [
                        "predicate: rate_point_change <= 0 (artış göstermeyen gruplar)"
                    ]
                intelligence["required_columns"] = catalog.required_columns_for(
                    intelligence["metrics"], intelligence["dimensions"]
                )
                if strategy.cohort:
                    for column in ("CreatedDate", "BaslangicTarihi"):
                        if column not in intelligence["required_columns"]:
                            intelligence["required_columns"].append(column)
                if (
                    strategy.current_period or strategy.baseline_period
                ) and "BaslangicTarihi" not in intelligence["required_columns"]:
                    # Period comparisons always run on the appointment time axis.
                    intelligence["required_columns"].append("BaslangicTarihi")

            planned_metrics = self._planned_metrics(intelligence["metrics"])
            planned_dimensions = self._planned_dimensions(intelligence["dimensions"])

            matched_examples: list[str] = []
            if intelligence["answerable"]:
                matched_examples = [
                    example.id
                    for example in examples.retrieve_examples(
                        question,
                        intelligence["analysis_type"],
                        intelligence["metrics"],
                        intelligence["dimensions"],
                        has_date_filter=bool(date_filters),
                    )
                ]
            if intelligence["analysis_type"]:
                signals_type = intelligence["analysis_type"]
            else:
                signals_type = signals.analysis_type
            if intelligence["aggregation"]:
                aggregation = intelligence["aggregation"]
            if group_column and intelligence["dimensions"]:
                # The catalog-resolved canonical GROUP BY dimension(s) (from
                # column_intelligence.json, e.g. "doktor bazinda" -> DoktorId)
                # supersede the separately-derived view-concepts display
                # column (view_semantics.json, deliberately id-averse) for
                # the SAME grouping phrase — projection must never lag behind
                # the final canonical grouping decision, for any dimension
                # family (doctor/department/branch/status/...), not just
                # DoktorId.
                projection = list(intelligence["dimensions"])
            elif intelligence["projection"]:
                projection = intelligence["projection"]
            elif (
                intelligence["dimensions"]
                and intelligence["metrics"]
                and projection
                and projection[0] not in intelligence["dimensions"]
            ):
                # A grouped aggregate can only project its GROUP BY columns; a
                # leftover concept display column from the bare noun mention
                # ("Bölümlerin doktor sayıları" -> 'doktor' display column)
                # would fail compliance against the deterministic SQL.
                projection = list(intelligence["dimensions"])
            if intelligence.get("scalar_distinct_count"):
                # "Kaç doktor var?" answers with one scalar — the display
                # column detected from the bare noun mention must not linger
                # as a projection the compliance validator would then demand.
                projection = []

            periods = self._comparison_periods(
                analysis,
                date_filters,
                intelligence["analysis_type"],
            )

            plan = QueryPlan(
                question=question,
                output_entity=output_entity,
                fact_entity=fact_entity,
                output_table=output_table,
                fact_table=fact_table,
                date_filters=date_filters,
                periods=periods,
                department_filter=signals.department,
                scope=scope,
                branch_filters=[],
                generic_scope_phrase_detected=generic_scope_phrase,
                extra_filters=extra_filters,
                aggregation=aggregation,
                ranking=ranking,
                limit=analysis.detected_limit,
                order=order,
                analysis_type=signals_type,
                join_path=join_path,
                projection=projection,
                distinct=distinct,
                metrics=intelligence["metrics"],
                dimensions=intelligence["dimensions"],
                planned_metrics=planned_metrics,
                planned_dimensions=planned_dimensions,
                numerator=intelligence["numerator"],
                denominator=intelligence["denominator"],
                grouping_granularity=intelligence["granularity"],
                comparisons=intelligence["comparisons"],
                derived_calculations=intelligence["derived"],
                required_columns=intelligence["required_columns"],
                answerable=intelligence["answerable"],
                answerability_reason=intelligence["answerability_reason"],
                confidence=intelligence["confidence"],
                matched_examples=matched_examples,
                question_goal=strategy.question_goal if strategy else None,
                current_period=strategy.current_period if strategy else None,
                baseline_period=strategy.baseline_period if strategy else None,
                cohort=strategy.cohort if strategy else None,
                minimum_sample_size=strategy.minimum_sample_size if strategy else None,
                assumptions=(strategy.assumptions if strategy else []) + scope_assumptions,
                planner_ms=(time.perf_counter() - start) * 1000,
            )
            self._log_plan(plan)
            return plan

        plan = QueryPlan(
            question=question,
            output_entity=output_entity,
            fact_entity=fact_entity,
            output_table=output_table,
            fact_table=fact_table,
            date_filters=date_filters,
            periods=self._comparison_periods(analysis, date_filters, signals.analysis_type),
            department_filter=signals.department,
            scope=scope,
            branch_filters=[],
            generic_scope_phrase_detected=generic_scope_phrase,
            extra_filters=extra_filters,
            aggregation=aggregation,
            ranking=ranking,
            limit=analysis.detected_limit,
            order=order,
            analysis_type=signals.analysis_type,
            join_path=join_path,
            projection=projection,
            distinct=distinct,
            assumptions=scope_assumptions,
            planner_ms=(time.perf_counter() - start) * 1000,
        )
        self._log_plan(plan)
        return plan

    # ── Entity resolution ────────────────────────────────────────────────

    def _entities(
        self, analysis: QueryAnalysis, folded_question: str
    ) -> tuple[str | None, str | None]:
        """Determines output and fact entities from mention order.

        Turkish is verb-final: the requested object sits closest to the action
        verb at the end, so the LAST mentioned non-department entity is the
        output and the FIRST mentioned one is the fact being filtered over.
        """
        positioned: list[tuple[int, str]] = []
        for entity in analysis.entities:
            position = folded_question.find(entity.normalized_text)
            positioned.append((position if position >= 0 else 0, entity.entity_type))
        positioned.sort()

        non_department = [name for _, name in positioned if name != "Department"]
        has_department = any(name == "Department" for _, name in positioned)

        if non_department:
            output = non_department[-1]
            fact = non_department[0]
        elif has_department:
            output = "Department"
            fact = "Department"
        else:
            return None, None

        # "En yoğun bölüm/doktor" ranks by appointment volume — when no fact
        # entity is stated, appointments are the implied fact.
        if fact == output and any(m in folded_question for m in _VOLUME_RANKING_MARKERS):
            if output != "Appointment":
                fact = "Appointment"
        return output, fact

    @staticmethod
    def _planned_metrics(metric_ids: list[str]) -> list[PlannedMetric]:
        by_id = catalog.load_metric_catalog().by_id()
        planned = []
        for metric_id in metric_ids:
            metric = by_id.get(metric_id)
            if metric is None:
                continue
            planned.append(
                PlannedMetric(
                    metric_id=metric.id,
                    aggregation_type=metric.formula_type,
                    format_type=metric.result_type,
                    source_columns=list(metric.required_columns),
                )
            )
        return planned

    @staticmethod
    def _planned_dimensions(dimensions: list[str]) -> list[PlannedDimension]:
        # Deferred import: app.context's package __init__ eagerly imports the
        # full context engine, which itself imports back into app.planning —
        # importing at call time (after both packages have finished their own
        # module-level imports) avoids the circular-import failure.
        from app.context.analytical_signals import column_to_dimension

        return [
            PlannedDimension(column=column, canonical_name=column_to_dimension(column))
            for column in dimensions
        ]

    def _resolve_intelligence(
        self,
        folded: str,
        analysis: QueryAnalysis,
        projection: list[str],
        aggregation: str | None,
        ranking: str | None,
        status_value: str | None = None,
    ) -> dict:
        """Catalog-driven analytical resolution (Agent Intelligence Foundation).

        Deterministically resolves metrics, dimensions, analysis pattern, time
        granularity, period comparisons, derived calculations, and answerability
        from the central catalogs. Never calls an LLM.
        """
        answerable, reason, alternative = catalog.check_answerability(folded)
        metrics = catalog.match_metrics(folded)
        dimensions = catalog.match_dimensions(folded)

        # Measure-phrase fallback: a status concept was independently resolved
        # (view_mapping.resolve_status_filter) and the utterance carries a
        # generic count/total/ratio request ("say", "toplamını", "adedini",
        # "oranı", ...) that no metric SYNONYM phrase covers ("Bekleyenleri
        # say." never matches waiting_count's "beklemede olan"/"bekleyen
        # randevu" synonyms). Separate concerns: status/entity resolution
        # (view_mapping, already ran), measure-request detection
        # (catalog.detect_measure_request, generic wording only), and metric
        # selection (catalog.metrics_for_status_value, catalog-authoritative
        # — only applied when exactly one candidate exists, never invented).
        if not metrics and status_value:
            measure_kind = catalog.detect_measure_request(folded)
            if measure_kind:
                candidates = catalog.metrics_for_status_value(
                    status_value, rate=(measure_kind == "rate")
                )
                if len(candidates) == 1:
                    metrics = candidates
        date_range_count = len(analysis.detected_dates)
        pattern = catalog.match_pattern(folded, date_range_count)

        # "X orani" text alone pattern-matches to "ratio" even when no specific
        # ratio metric (numerator/denominator) exists for it - e.g. "kadin
        # erkek orani" has no percent-of-total metric defined, unlike
        # "gerceklesme orani". Without a matched metric, "ratio" has nothing to
        # compute; fall back to a grouped distribution over the resolved
        # dimension instead of emitting an unanswerable empty-metric plan.
        if pattern == "ratio" and not metrics and dimensions:
            pattern = "distribution"

        granularity = catalog.match_granularity(folded)
        comparisons = catalog.detect_period_comparison(folded, date_range_count)

        derived: list[str] = []
        if catalog.detect_age_group_request(folded):
            derived.append(catalog.AGE_GROUP_DERIVATION)
            if "DogumTarihi" not in dimensions:
                dimensions = dimensions + ["DogumTarihi"]

        # Structural upgrades: two grouping dimensions mean a cross analysis, a
        # time bucket means a trend, and a detected period comparison overrides
        # generic counting — regardless of which keyword triggered first.
        generic_patterns = (None, "count", "distinct_count", "distribution")
        if comparisons and pattern in generic_patterns + ("time_trend",):
            pattern = "period_comparison"
        elif granularity and pattern in generic_patterns:
            pattern = "time_trend"
        elif len(dimensions) >= 2 and pattern in generic_patterns:
            pattern = "cross_analysis"
        elif dimensions and not metrics and pattern is None:
            pattern = "distribution"
        if pattern in ("period_comparison", "percentage_change") and not comparisons:
            comparisons = ["current_period_vs_previous_period"]

        # A trend question ("randevu eğilimini özetle") carries no explicit
        # granularity KEYWORD ("aylık"/"haftalık") but its relative date range
        # ("son 6 ay") already resolved a granularity via the date detector —
        # reuse that instead of defaulting to no time bucket at all, which
        # previously collapsed every trend question with no explicit
        # granularity wording to a single scalar COUNT(*).
        if pattern == "time_trend" and granularity is None:
            granularity = self._trend_granularity_from_dates(analysis.detected_dates)

        # Volume is the implied metric for count-like patterns with no explicit metric.
        if not metrics and (
            aggregation
            or pattern
            in (
                "count",
                "distinct_count",
                "ranking",
                "top_n",
                "bottom_n",
                "distribution",
                "cross_analysis",
                "time_trend",
                "period_comparison",
                "percentage_change",
                "duration_analysis",
                "data_quality",
            )
        ):
            metrics = ["appointment_count"]

        # A time bucket upgrades the plain volume metric to its bucketed variant.
        _BUCKETED_COUNTS = {
            "day": "daily_appointment_count",
            "week": "weekly_appointment_count",
            "month": "monthly_appointment_count",
        }
        if granularity in _BUCKETED_COUNTS and metrics == ["appointment_count"]:
            metrics = [_BUCKETED_COUNTS[granularity]]

        by_id = catalog.load_metric_catalog().by_id()
        primary = by_id.get(metrics[0]) if metrics else None
        numerator = denominator = None
        if primary is not None:
            if primary.numerator and primary.denominator:
                numerator, denominator = primary.numerator, primary.denominator
            if primary.analysis_type == "data_quality" and pattern in (
                None,
                "count",
                "duration_analysis",
            ):
                pattern = primary.analysis_type
            elif pattern is None:
                pattern = primary.analysis_type
            if granularity is None and primary.grouping_granularity:
                granularity = primary.grouping_granularity
            if primary.fixed_dimension and primary.fixed_dimension not in dimensions:
                dimensions = dimensions + [primary.fixed_dimension]

        # A pure "kaç X var" distinct count counts the SAME concept whose bare
        # noun mention would otherwise become a grouping dimension ("Kaç doktor
        # var?" -> 'doktor' also matched GenelRandevuKaynakAdi). Without
        # explicit grouping wording the dimension is an artifact of the
        # mention, not a requested breakdown — drop it so the question answers
        # with a single scalar instead of hundreds of per-group rows.
        scalar_distinct_count = False
        if (
            primary is not None
            and primary.formula_type == "count_distinct"
            and not any(
                marker in folded
                for marker in ("gore", "bazinda", "bazli", "kirilim", "dagilim")
            )
        ):
            self_columns = set(primary.required_columns) | _SELF_COUNT_DIMENSIONS.get(
                primary.id, set()
            )
            dimensions = [d for d in dimensions if d not in self_columns]
            scalar_distinct_count = not dimensions

        # The final metric catalog definition is the sole source of truth for
        # aggregation: whenever a primary metric with a formula was matched,
        # its formula supersedes any earlier generic aggregation guess —
        # generic for every formula_type (conditional_count/conditional_rate
        # included), not an allow-listed subset. DeterministicSQLBuilder
        # already renders every metric from its own catalog formula
        # regardless of plan.aggregation, so leaving a stale generic guess
        # (e.g. "COUNT(*)") here would only mislead the LLM prompt and
        # PlanComplianceValidator's aggregation check.
        resolved_aggregation = None
        if primary is not None and primary.formula:
            resolved_aggregation = primary.formula

        resolved_projection: list[str] = []
        display_dimensions = [d for d in dimensions if not d.lower().endswith("id")]
        if display_dimensions and not projection:
            resolved_projection = display_dimensions[:2]

        confidence = min(
            1.0,
            0.4
            + (0.2 if metrics else 0.0)
            + (0.2 if pattern else 0.0)
            + (0.2 if dimensions else 0.0),
        )
        answerability_reason = None
        if not answerable:
            answerability_reason = f"{reason} {alternative}".strip()
            confidence = 0.2

        return {
            "metrics": metrics,
            "dimensions": dimensions,
            # Scalar distinct count ("Kaç doktor var?"): the answer is one
            # number; any concept display column detected from the bare noun
            # must not survive as a projection either.
            "scalar_distinct_count": scalar_distinct_count,
            "analysis_type": pattern,
            "numerator": numerator,
            "denominator": denominator,
            "granularity": granularity,
            "comparisons": comparisons,
            "derived": derived,
            "required_columns": catalog.required_columns_for(metrics, dimensions),
            "answerable": answerable,
            "answerability_reason": answerability_reason,
            "confidence": confidence,
            "aggregation": resolved_aggregation,
            "projection": resolved_projection,
        }

    def _view_output_entity(self, analysis: QueryAnalysis, output_entity: str | None) -> str | None:
        """Adjusts the output entity for view-column resolution.

        'En çok randevu oluşturan kişileri göster' detects both Creator
        ('randevu oluşturan') and Patient (via the generic word 'kişi'); the
        requested output is the creator, never the patient.
        """
        if output_entity != "Patient":
            return output_entity
        entity_types = {entity.entity_type for entity in analysis.entities}
        if "Creator" not in entity_types:
            return output_entity
        patient_terms = {
            entity.normalized_text
            for entity in analysis.entities
            if entity.entity_type == "Patient"
        }
        if patient_terms and patient_terms <= {"kisi"}:
            return "Creator"
        return output_entity

    def _raw_list_request(self, analysis: QueryAnalysis, folded_question: str) -> bool:
        if "LIST" not in analysis.detected_operations:
            return False
        if any(operation in analysis.detected_operations for operation in ("COUNT", "SUM", "AVG")):
            return False
        ranking_markers = (
            *_VOLUME_RANKING_MARKERS,
            *_ASCENDING_MARKERS,
            *_GENERIC_RANKING_MARKERS,
        )
        if any(marker in folded_question for marker in ranking_markers):
            return False
        if analysis.detected_order and analysis.detected_limit:
            return True
        if any(marker in folded_question for marker in ("gore", "bazinda", "dagilim", "oran")):
            return False
        if any(
            marker in folded_question
            for marker in ("trend", "egilim", "aylik", "gunluk", "haftalik")
        ):
            return False
        if "randevu" in folded_question:
            return True
        return bool(analysis.detected_limit)

    def _view_list_projection(self, view_name: str) -> list[str]:
        columns = view_mapping.get_view_entry(view_name).get("columns", {})
        preferred = [
            "Id",
            "BaslangicTarihi",
            "BitisTarihi",
            "RandevuDurumu",
            "GenelRandevuKaynakAdi",
            "GenelRandevuBolumAdi",
            "SubeAdi",
            "RandevuTipiAdi",
        ]
        return [column for column in preferred if column in columns]

    def _view_group_dimension(self, folded_question: str, view_name: str) -> str | None:
        """Resolves 'X bazında / X'e göre' grouping wording to a descriptive view column."""
        concepts = view_mapping.get_view_entry(view_name).get("concepts", {})
        for match in _GROUP_BY_PATTERN.finditer(folded_question):
            word = match.group(1)
            for spec in concepts.values():
                column = spec.get("column")
                if not column or column.lower().endswith("id"):
                    continue
                for term in spec.get("terms", []):
                    folded_term = view_mapping.fold(term)
                    if " " in folded_term:
                        continue
                    if word.startswith(folded_term):
                        return column
        return None

    def _entity_table(
        self, entity: str | None, table_map: dict[str, "TableMetadata"]
    ) -> str | None:
        if entity is None:
            return None
        table_name = _ENTITY_TABLES.get(entity)
        if table_name and table_name in table_map:
            return table_name
        return table_name  # keep the mapping even if the retriever omitted it

    # ── Constraints ──────────────────────────────────────────────────────

    def _date_filters(
        self,
        analysis: QueryAnalysis,
        anchor_table: str | None,
        table_map: dict[str, "TableMetadata"],
    ) -> list[DateFilterPlan]:
        column = self._date_column(anchor_table, table_map)
        return [
            DateFilterPlan(
                expression=date_range.expression,
                start_date=date_range.start_date.isoformat(),
                end_date=date_range.end_date.isoformat(),
                column=column,
            )
            for date_range in analysis.detected_dates
        ]

    def _comparison_periods(
        self,
        analysis: QueryAnalysis,
        date_filters: list[DateFilterPlan],
        analysis_type: str | None,
    ) -> list[PeriodPlan]:
        """Carries exactly two parser periods into the plan as half-open ranges."""
        if analysis_type not in _PERIOD_ANALYSIS_TYPES or len(analysis.detected_dates) != 2:
            return []

        periods: list[PeriodPlan] = []
        for detected, date_filter in zip(analysis.detected_dates, date_filters, strict=True):
            periods.append(
                PeriodPlan(
                    label=self._period_label(detected),
                    start_inclusive=detected.start_date.isoformat(),
                    end_exclusive=(detected.end_date + timedelta(days=1)).isoformat(),
                    column=date_filter.column,
                )
            )
        return periods

    def _trend_granularity_from_dates(self, detected_dates: list) -> str:
        """Deterministically picks a time bucket from the requested date span.

        Never guesses from question wording — only from the already-resolved
        date range(s). day: up to 31 days. week: 32-120 days. month: 121-730
        days (~4-24 months). year: longer ranges. A trend question with no
        detected date range at all (no explicit period mentioned) defaults to
        month, the most common trend-reporting cadence.
        """
        if not detected_dates:
            return "month"
        span = detected_dates[0]
        days = (span.end_date - span.start_date).days + 1
        if days <= 31:
            return "day"
        if days <= 120:
            return "week"
        if days <= 730:
            return "month"
        return "year"

    def _period_label(self, period) -> str:
        folded_expression = self._extractor.fold(period.expression)
        if period.granularity == "month" and not any(
            marker in folded_expression for marker in ("bu ay", "gecen ay")
        ):
            return f"{_MONTH_LABELS[period.start_date.month]} {period.start_date.year}"
        if period.granularity == "year" and re.fullmatch(r"\d{4}", period.expression):
            return period.expression
        return period.expression.strip()

    def _date_column(
        self, table_name: str | None, table_map: dict[str, "TableMetadata"]
    ) -> str | None:
        table = table_map.get(table_name or "")
        if not table:
            return None
        for col in table.columns:
            lowered = col.name.lower()
            if "tarih" in lowered or "date" in lowered:
                return col.name
        return None

    def _aggregation(self, analysis: QueryAnalysis) -> str | None:
        for operation in ("COUNT", "SUM", "AVG"):
            if operation in analysis.detected_operations:
                return operation
        return None

    def _ranking(
        self,
        analysis: QueryAnalysis,
        analysis_type: str | None,
        folded_question: str,
    ) -> tuple[str | None, str | None]:
        order = analysis.detected_order
        if analysis_type == "ranking":
            direction = (
                "ASC" if any(marker in folded_question for marker in _ASCENDING_MARKERS) else "DESC"
            )
            return direction, order
        return (order, order) if order else (None, None)

    def _extra_filters(self, folded_question: str) -> list[str]:
        filters: list[str] = []
        if _NEGATION_PATTERN.search(folded_question):
            filters.append("NEGATION: exclude matching rows (NOT EXISTS or LEFT JOIN ... IS NULL)")
        return filters

    def _detect_generic_scope(self, folded_question: str) -> str | None:
        """Returns the matched generic organization-wide scope wording, or None.

        This is a SCOPE signal only ('no specific branch, whole organization')
        — it never produces a branch value filter. A real branch value may
        only ever come from a grounded catalog/database lookup (see
        QueryPlan.branch_filters docstring); no such lookup exists in this
        codebase today, so branch_filters stays empty regardless of this match.
        """
        match = _GENERIC_SCOPE_ALL_PATTERN.search(folded_question)
        return match.group(0).strip() if match else None

    # ── Relationship planning ────────────────────────────────────────────

    def _join_path(
        self,
        fact_table: str | None,
        output_table: str | None,
        department_filter: str | None,
        table_map: dict[str, "TableMetadata"],
    ) -> list[JoinStep]:
        """Minimal FK path: fact -> output, extended to bolumler for department filters.

        Paths come only from declared foreign keys — joins are never guessed.
        """
        steps: list[JoinStep] = []
        adjacency = self._fk_adjacency(table_map)

        if fact_table and output_table and fact_table != output_table:
            steps.extend(self._shortest_path(fact_table, output_table, adjacency))

        if department_filter and _DEPARTMENT_TABLE in table_map:
            covered = {fact_table, output_table}
            covered.update(step.from_table for step in steps)
            covered.update(step.to_table for step in steps)
            if _DEPARTMENT_TABLE not in covered:
                for anchor in (output_table, fact_table):
                    if not anchor:
                        continue
                    extension = self._shortest_path(anchor, _DEPARTMENT_TABLE, adjacency)
                    if extension:
                        steps.extend(extension)
                        break
        return steps

    def _fk_adjacency(self, table_map: dict[str, "TableMetadata"]) -> dict[str, list[JoinStep]]:
        """Undirected FK adjacency; each edge keeps the true FK owner direction."""
        adjacency: dict[str, list[JoinStep]] = {name: [] for name in table_map}
        for table in table_map.values():
            for fk in table.foreign_keys:
                if fk.referred_table not in table_map:
                    continue
                step = JoinStep(
                    from_table=table.name,
                    from_column=fk.constrained_columns[0] if fk.constrained_columns else "",
                    to_table=fk.referred_table,
                    to_column=fk.referred_columns[0] if fk.referred_columns else "id",
                )
                adjacency[table.name].append(step)
                adjacency[fk.referred_table].append(step)
        return adjacency

    def _shortest_path(
        self,
        source: str,
        target: str,
        adjacency: dict[str, list[JoinStep]],
    ) -> list[JoinStep]:
        if source not in adjacency or target not in adjacency:
            return []
        queue: deque[str] = deque([source])
        parents: dict[str, tuple[str, JoinStep]] = {}
        visited = {source}
        while queue:
            current = queue.popleft()
            if current == target:
                break
            for step in adjacency.get(current, []):
                neighbor = step.to_table if step.from_table == current else step.from_table
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                parents[neighbor] = (current, step)
                queue.append(neighbor)
        if target not in parents and source != target:
            return []
        path: list[JoinStep] = []
        node = target
        while node != source:
            parent, step = parents[node]
            path.append(step)
            node = parent
        path.reverse()
        return path

    # ── Projection ───────────────────────────────────────────────────────

    def _projection(
        self, output_table: str | None, table_map: dict[str, "TableMetadata"]
    ) -> list[str]:
        table = table_map.get(output_table or "")
        if not table:
            return []
        column_names = [col.name for col in table.columns]
        for candidate in _DESCRIPTIVE_PRIORITY:
            if candidate in column_names:
                return [candidate]
        for name in column_names:
            if name.lower().endswith("_adi"):
                return [name]
        non_ids = [n for n in column_names if n != "id" and not n.endswith("_id")]
        return non_ids[:1]

    # ── Logging ──────────────────────────────────────────────────────────

    def _log_plan(self, plan: QueryPlan) -> None:
        logger.info(
            "\n================ QUERY PLAN (AG-022) ================\n"
            f"Question   : {plan.question}\n"
            f"Output     : {plan.output_entity} ({plan.output_table})\n"
            f"Fact       : {plan.fact_entity} ({plan.fact_table})\n"
            f"Dates      : "
            f"{[f'{d.expression} {d.start_date}..{d.end_date}' for d in plan.date_filters]}\n"
            f"Department : {plan.department_filter or 'none'}\n"
            f"Extra      : {plan.extra_filters or 'none'}\n"
            f"Aggregation: {plan.aggregation or 'none'}  Ranking: {plan.ranking or 'none'}  "
            f"Limit: {plan.limit or 'none'}\n"
            f"Join Path  : {' | '.join(s.render() for s in plan.join_path) or 'none'}\n"
            f"Projection : {plan.projection or 'none'}  Distinct: {plan.distinct}\n"
            f"Planner    : {plan.planner_ms:.2f} ms  Constraints: {plan.constraint_count()}\n"
            "=====================================================",
            extra={
                "query_plan": plan.model_dump(),
                "planner_ms": plan.planner_ms,
                "constraint_count": plan.constraint_count(),
                # AI-INTELLIGENCE-015 diagnostics — safe (dates/flags/column
                # names only, never patient-level data).
                "explicit_date_expression": (
                    plan.date_filters[0].expression if plan.date_filters else None
                ),
                "resolved_date_range": (
                    f"{plan.date_filters[0].start_date}..{plan.date_filters[0].end_date}"
                    if plan.date_filters
                    else None
                ),
                "scope_mode": plan.scope,
                "branch_dimension_requested": "SubeAdi" in plan.dimensions,
                "branch_filter_values": plan.branch_filters,
                "branch_filter_grounded": bool(plan.branch_filters),
                "generic_scope_phrase_detected": plan.generic_scope_phrase_detected,
            },
        )


def format_plan_for_prompt(plan: QueryPlan) -> str:
    """Renders the QueryPlan as a compact contract section for the SQL prompt."""
    lines: list[str] = ["Plan (implement every item):"]
    if plan.output_table:
        projection = f".{plan.projection[0]}" if plan.projection else ""
        distinct = " DISTINCT" if plan.distinct else ""
        lines.append(f"- Output:{distinct} {plan.output_table}{projection}")
    if plan.fact_table and plan.fact_table != plan.output_table:
        lines.append(f"- From: {plan.fact_table}")
    if plan.join_path:
        joins = "; ".join(step.render() for step in plan.join_path)
        lines.append(f"- Joins: {joins}")
    if plan.periods:
        for role, period in zip(("baseline", "current"), plan.periods, strict=True):
            column = period.column or "the date column"
            lines.append(
                f"- {role.title()} period ({period.label}): "
                f"{column} >= '{period.start_inclusive}' AND "
                f"{column} < '{period.end_exclusive}'"
            )
    else:
        for date_filter in plan.date_filters:
            column = date_filter.column or "the date column"
            # Half-open range even for a single explicit day ("bugün"): the date
            # column is DATETIME, so an exact '=' equality would silently match
            # almost nothing. Never render as a relative DATEADD lookback offset
            # either — this IS the explicit, already-resolved date; it must
            # appear as its own literal boundary, not be re-derived by the LLM.
            lines.append(
                f"- Filter: {column} >= '{date_filter.start_date}' AND "
                f"{column} < DATEADD(day, 1, '{date_filter.end_date}')"
            )
    if plan.scope == "all":
        lines.append(
            "- Scope: organization-wide — the question used a generic phrase "
            f"('{plan.generic_scope_phrase_detected}'), NOT a specific branch name. "
            "Do NOT add a SubeAdi filter (no WHERE/LIKE on SubeAdi values)."
        )
    if plan.branch_filters:
        values = ", ".join(f"'{value}'" for value in plan.branch_filters)
        lines.append(f"- Filter: SubeAdi IN ({values})")
    if plan.resolved_filters:
        # AI-INTELLIGENCE-016: grounded filters for fields other than branch
        # (which is rendered above) — department is rendered via the legacy
        # `department_filter` line below to avoid a duplicate predicate.
        from app.database_intelligence.value_catalog import FIELD_COLUMNS

        for field_name, resolved in plan.resolved_filters.items():
            if field_name in ("branch", "department"):
                continue
            if not resolved.grounded or not resolved.values:
                continue
            column, _tier = FIELD_COLUMNS.get(field_name, (None, None))
            if not column:
                continue
            values = ", ".join(f"'{value}'" for value in resolved.values)
            lines.append(f"- Filter: {column} IN ({values})")
    if plan.department_filter:
        # GenelRandevuBolumAdi holds comma-separated composites ("Genel
        # Cerrahi, Ameliyathane, ") — equality on the raw value never matches.
        lines.append(
            "- Filter: department (GenelRandevuBolumAdi is comma-separated; use "
            "delimiter-bounded containment): "
            f"',' + REPLACE(GenelRandevuBolumAdi, ', ', ',') + ',' "
            f"LIKE N'%,{plan.department_filter},%'"
        )
    for extra in plan.extra_filters:
        lines.append(f"- Filter: {extra}")
    if plan.aggregation:
        lines.append(f"- Aggregate: {plan.aggregation}")
    if plan.metrics:
        formula_lines = catalog.metric_formula_lines(plan.metrics)
        if formula_lines:
            lines.append("- Metrics (use these exact formulas):")
            lines.extend(f"  {formula_line}" for formula_line in formula_lines)
    if plan.numerator and plan.denominator:
        lines.append(
            f"- Ratio: 100.0 * {plan.numerator} / NULLIF({plan.denominator}, 0) "
            f"(conditional aggregation, null-safe division)"
        )
    if plan.dimensions:
        lines.append(f"- Group by: {', '.join(plan.dimensions)}")
    if plan.grouping_granularity:
        lines.append(f"- Time bucket: {plan.grouping_granularity} (chronological ORDER BY)")
    if plan.comparisons:
        lines.append(f"- Compare periods: {', '.join(plan.comparisons)}")
    for derivation in plan.derived_calculations:
        lines.append(f"- Derived: {derivation}")
    if plan.ranking:
        lines.append(f"- Order: {plan.ranking} (ORDER BY required)")
    if plan.limit:
        lines.append(f"- Limit: {plan.limit} rows (T-SQL: SELECT TOP ({plan.limit}) ...)")
    if plan.question_goal:
        lines.extend(
            reasoning.format_strategy_for_prompt(
                {
                    "question_goal": plan.question_goal,
                    "current_period": plan.current_period,
                    "baseline_period": plan.baseline_period,
                    "cohort": plan.cohort,
                    "minimum_sample_size": plan.minimum_sample_size,
                }
            )
        )
    if plan.matched_examples:
        by_id = {example.id: example for example in examples.load_golden_dataset().questions}
        matched = [by_id[eid] for eid in plan.matched_examples if eid in by_id]
        example_block = examples.format_examples_for_prompt(matched)
        if example_block:
            lines.append(example_block)
    return "\n".join(lines) if len(lines) > 1 else ""
