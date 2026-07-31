import logging
import re
import time
from collections import deque
from datetime import date, timedelta
from typing import TYPE_CHECKING

from app.application_models.query_analysis import QueryAnalysis
from app.context.extractor import ContextExtractor
from app.planning.models import (
    AggregateThreshold,
    DateFilterPlan,
    JoinStep,
    PeriodPlan,
    PlannedDimension,
    PlannedMetric,
    QueryPlan,
)
from app.reporting.presentation import get_dimension_label
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

# Relationship metrics use some dimensions as the condition itself. A bare noun
# in "different branches" or "multiple services" should not become a GROUP BY
# unless the user explicitly asks for a breakdown by that same dimension.
_RELATIONSHIP_CONDITION_DIMENSIONS: dict[str, set[str]] = {
    "cross_branch_repeat_patient_count": {"SubeAdi"},
    "same_day_multi_service_patient_count": {"HizmetAdi"},
    "same_day_multi_doctor_patient_count": {"DoktorId", "GenelRandevuKaynakAdi"},
}

_NEGATION_PATTERN = re.compile(r"\b(olmayan|bulunmayan|almayan)\w*\b|\bhic\b")
# "elemek" = to eliminate ("1000 altındaki hekimleri ELE"), an exclusion that
# inverts an aggregate threshold. Guarded against "ele al-" ("bunu ele alalım"
# = let's consider this), which is the opposite of an exclusion.
_ELIMINATE_MARKER = re.compile(r"\bele\b(?!\s+al)|\beleyip\b|\belenen\b")

# Sentinel dimension name for the weekday/weekend derived grouping — not a real
# view column; the SQL builder renders it as a DATEDIFF-based CASE expression
# gated on catalog.DAY_TYPE_DERIVATION (mirrors the DogumTarihi age-group gate).
_DAY_TYPE_DIMENSION = "DayType"

# Bare single-sided gender reference ("kadin hasta orani") - distinct from the
# two-word "kadin erkek orani" phrasing already covered by the CinsiyetId
# dimension synonym list.
_BARE_GENDER_TERM_PATTERN = re.compile(r"\b(kadin|erkek)\b")

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

# The specific word forms of "durum" (status) that _GROUP_BY_PATTERN must
# capture for a "bazında"/"göre" marker to genuinely mean "group by status" -
# any OTHER marker elsewhere in the same sentence ("aylar bazında") must not
# count as license to keep RandevuDurumu as a dimension (see the status-value
# stripping block in _resolve_intelligence).
_STATUS_GROUPING_WORDS = {"durum", "duruma", "durumu", "durumuna", "durumda"}

_MONTH_BUCKET_RANKING_PATTERN = re.compile(
    r"\bay\w*\b.*\b(?:sirala\w*|en\s+(?:yuksek|fazla|cok|dusuk|az)|ilk\s+\d+)\b"
    r"|\b(?:sirala\w*|en\s+(?:yuksek|fazla|cok|dusuk|az)|ilk\s+\d+)\b.*\bay\w*\b"
)

_ASCENDING_MARKERS = (
    "artan sirala",
    "artan olarak sirala",
    "en az",
    "en dusuk",
    "en dusukten yuksege",
    "dusukten yuksege",
    "azdan coga",
    "azdan coka",
    "en seyrek",
)
_ORDER_ASC_MARKERS = (
    "artan sirala",
    "artan olarak sirala",
    "kucukten buyuge",
    "en dusukten yuksege",
    "dusukten yuksege",
    "azdan coga",
    "azdan coka",
)
_ORDER_DESC_MARKERS = (
    "azalan sirala",
    "azalan olarak sirala",
    "buyukten kucuge",
    "coktan aza",
)

_DESCRIPTIVE_PRIORITY = ("ad_soyad", "bolum_adi", "sirket_adi", "test_adi", "name", "title")

_PERIOD_ANALYSIS_TYPES = {
    "period_comparison",
    "baseline_comparison",
    "adaptive_time_comparison",
    "percentage_change",
}
_PERIOD_COMPARISON_MARKERS = ("degisim", "degis", "fark", "kiyas", "kiyasla", "karsilastir")
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
        aggregate_threshold = self._aggregate_threshold(folded)
        percentile = self._percentile(question, folded)
        compound_secondary = self._compound_secondary_clause(question, folded)
        if compound_secondary:
            scope_assumptions = scope_assumptions + [
                "Bu soru birden fazla bölüm içeriyor; yalnızca ilk kısmı yanıtlandı. "
                f"Şunu ayrıca sorabilirsiniz: “{compound_secondary}”."
            ]
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

            # Explicit exclusion of NAMED statuses ("Beklemede ve İşlem Sürmekte
            # olanları HARİÇ TUT") takes precedence over positive status
            # resolution: the named statuses must NOT become a positive filter
            # or drive a conditional metric (waiting_count/in_progress_count) —
            # the intent is the COMPLEMENT. Rendered as the same equality/IN
            # path as the single-word negation below.
            excluded_status_values = view_mapping.resolve_excluded_status_values(
                folded, view_name
            )
            if excluded_status_values is not None:
                status_column_name = view_mapping.status_column(view_name)
                extra_filters = extra_filters + [
                    f"{status_column_name} = '{value}'" for value in excluded_status_values
                ]
                status_filter = None
                status_value = None
            else:
                status_filter = view_mapping.resolve_status_filter(folded, view_name)
                if status_filter:
                    extra_filters = extra_filters + [status_filter]
                status_value = view_mapping.resolve_status_value(folded, view_name)

                # Status negation ("gerçekleşmeyenler", "tamamlanmayan"): renders
                # as an IN-list over the complement statuses — the SAME
                # equality/IN rendering path already used for a positive status
                # filter, never a new '<>' predicate. Mutually exclusive with the
                # positive match above (a question naming both is contradictory).
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
                folded,
                analysis,
                projection,
                aggregation,
                ranking,
                status_value,
                department_filter=signals.department,
                department_column=view_mapping.concept_column("Department", view_name),
                status_column=view_mapping.status_column(view_name),
            )
            if aggregate_threshold is not None and intelligence["metrics"]:
                aggregate_threshold = aggregate_threshold.model_copy(
                    update={"metric": intelligence["metrics"][0]}
                )
                if (
                    intelligence["analysis_type"] == "bottom_n"
                    and aggregate_threshold.operator in {">", ">="}
                ):
                    intelligence["analysis_type"] = "ranking"
                    ranking = "DESC"
                    order = "DESC"
            # A percentile slice ("en üstteki %10") is a ranked TOP (N) PERCENT
            # cut. Its N was also mis-detected as a plain row limit — drop that.
            # The bottom direction ("en alttaki/en düşük %10") sorts ascending.
            if percentile is not None:
                if analysis.detected_limit == percentile:
                    analysis = analysis.model_copy(update={"detected_limit": None})
                is_bottom = any(
                    marker in folded
                    for marker in ("en alttaki", "alttaki", "en dusuk", "en az")
                )
                direction = "ASC" if is_bottom else "DESC"
                ranking = direction
                order = direction
                if intelligence["analysis_type"] in (None, "count", "distribution"):
                    intelligence["analysis_type"] = "ranking"
            # In an exclusion ("Beklemede ve İşlem Sürmekte olanları hariç tut"),
            # the named statuses also match their conditional metrics via the
            # catalog (beklemede -> waiting_count, işlem sürmekte ->
            # in_progress_count) — counting exactly what the user asked to
            # EXCLUDE. Drop any metric anchored to an excluded status so the
            # plan measures the neutral volume (appointment_count) over the
            # complement filter instead.
            if excluded_status_values is not None:
                kept_statuses = set(excluded_status_values)
                surviving = [
                    metric_id
                    for metric_id in intelligence["metrics"]
                    if (value := catalog.metric_status_value(metric_id)) is None
                    or value in kept_statuses
                ]
                surviving = surviving or ["appointment_count"]
                if surviving != intelligence["metrics"]:
                    intelligence["metrics"] = surviving
                    # The dropped status metric's SUM(CASE...) formula also lives
                    # in intelligence["aggregation"]; leaving it stale makes
                    # PlanComplianceValidator demand that SUM in SQL the builder
                    # no longer emits. Re-derive it from the surviving primary
                    # metric (appointment_count -> COUNT(*)).
                    by_id = catalog.load_metric_catalog().by_id()
                    primary = by_id.get(surviving[0])
                    intelligence["aggregation"] = (
                        primary.formula if primary and primary.formula else "COUNT(*)"
                    )
            # Age RANGE filter ("40 yaş üstü", "18 yaşından küçük", "30-40 yaş
            # arası"): a WHERE predicate on the derived age, NOT an age-group
            # breakdown. Because "yaş" is a DogumTarihi synonym it otherwise
            # became a GROUP BY dimension, bucketing by decade instead of
            # filtering (#4 çoklu-değer/ileri filtreler, 2026-07-29).
            age_filter = self._age_filter(folded)
            if age_filter:
                extra_filters = extra_filters + [age_filter]
                if not catalog.detect_age_group_request(folded):
                    intelligence["dimensions"] = [
                        dimension
                        for dimension in intelligence["dimensions"]
                        if dimension != "DogumTarihi"
                    ]
                intelligence["required_columns"] = list(
                    dict.fromkeys(intelligence["required_columns"] + ["DogumTarihi"])
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
            # Several status-differentiated metrics in one question ("toplam,
            # gerçekleşen ve gelmeyen randevu sayıları") each embed their OWN
            # status inside a SUM(CASE ...); the status word "gerçekleşen" also
            # resolved a GLOBAL status WHERE filter, which would exclude the
            # rows the OTHER metrics need — collapsing "toplam"/"gelmeyen" to
            # the completed count and zero (live UI 2026-07-30: gerçekleşen ==
            # toplam, gelmeyen == 0 for every department). When any planned
            # metric measures a different (or no) status than the global
            # filter, keep the status only in the per-metric CASE.
            elif (
                status_filter
                and status_value
                and any(
                    catalog.metric_status_value(metric_id) != status_value
                    for metric_id in intelligence["metrics"]
                )
            ):
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
            aggregation = intelligence["aggregation"]
            # Typo recovery: a mis-spelled grouping word ("bolm bazında") slips
            # past every exact matcher (dimensions stay empty). ONLY then try a
            # one-edit fuzzy recovery — never overriding a deliberate
            # no-dimension decision such as a single-metric period comparison
            # (robustness probe round 4, 2026-07-29).
            if not intelligence["dimensions"]:
                fuzzy_dimension = self._fuzzy_group_dimension(folded, view_name)
                if fuzzy_dimension:
                    intelligence["dimensions"] = [fuzzy_dimension]
                    if not group_column:
                        group_column = fuzzy_dimension
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
            if intelligence.get("scalar_distinct_count") or (
                intelligence["metrics"] and not intelligence["dimensions"]
            ):
                # Any true scalar answer (a metric with no GROUP BY dimension
                # — "Kaç doktor var?", but just as much a status-conditional
                # count like "Kardiyoloji bölümünde kaç tanesi gerçekleşti?")
                # answers with one row. The display column detected from the
                # bare noun mention ("bölüm" -> GenelRandevuBolumAdi) must not
                # linger as a projection: the deterministic SQL never selects
                # it (there is no GROUP BY to select it alongside), so
                # PlanComplianceValidator demanding it as a "missing
                # projection column" silently killed the whole answer
                # (2026-07-24, real UI bug report).
                projection = []
            if intelligence["analysis_type"] == "repeat_behavior":
                # Relationship CTE builders own their SELECT aliases. Keeping a
                # planner projection here makes the generic compliance checker
                # inspect the CTE's inner SELECT and falsely report the outer
                # dimension alias as missing.
                projection = []
                if not intelligence["dimensions"]:
                    ranking = None
                    order = None

            periods = self._comparison_periods(
                analysis,
                date_filters,
                intelligence["analysis_type"],
                folded,
            )
            # A two-period comparison with no grouping dimension answers with a
            # SINGLE row (current/baseline/change) — there is nothing to sort
            # and nothing to cap. Change wording ("düşüş", "artış") nonetheless
            # resolves a ranking direction, and an "ilk 5" from an EARLIER turn
            # survives in the session context; PlanComplianceValidator then
            # rejected the SQL for a missing "ORDER BY ... ASC" / "TOP (5)" that
            # can never exist there, killing the whole answer (Codex live UI
            # testing, 2026-07-31 — the most frequent error in the comparison
            # session).
            scalar_period_comparison = (
                len(periods) == 2
                and not intelligence["dimensions"]
                and intelligence["analysis_type"] in _PERIOD_ANALYSIS_TYPES
            )
            if scalar_period_comparison:
                ranking = None
                order = None

            # Naming THREE OR MORE separate years ("2022 2023 2024 2025 randevu
            # sayılarını tek tek ver") is itself the request to see them apart —
            # a structural signal that does not depend on catching the right
            # wording. Without it the windows were merged into one grand total
            # and then labelled with a single year, which reads as a wrong
            # answer (live UI testing, 2026-07-31). Two windows stay a
            # comparison; a plan that already groups is left alone.
            distinct_year_windows = {
                (date_filter.start_date, date_filter.end_date)
                for date_filter in date_filters
            }
            if (
                len(distinct_year_windows) >= 3
                and not intelligence["dimensions"]
                and not periods
                and intelligence["granularity"] is None
            ):
                intelligence["granularity"] = "year"
                intelligence["analysis_type"] = "time_trend"

            # Defense in depth: the deterministic time-series builder has no
            # TOP(N) support at all (a trend answers with every bucket in the
            # resolved date range, not "the first N rows"), so any row limit
            # reaching it would fail PlanComplianceValidator's generic
            # "plan.limit needs a matching TOP" check and kill the whole
            # answer. The one phrasing known to produce a bogus limit here
            # ("2025'in ilk 6 ayının ... trendini özetle", where "ilk 6"
            # qualifies MONTHS, not rows) is now fixed at its source in
            # `QueryAnalyzer._detect_limit_and_order`, which also resolves it
            # into a real partial-year date range — this guard stays for any
            # other wording that pairs an explicit row limit with a trend.
            resolved_limit = analysis.detected_limit
            if (
                resolved_limit is None
                and intelligence["granularity"] == "month"
                and intelligence["analysis_type"] in {"ranking", "top_n", "bottom_n"}
            ):
                month_limit = re.search(r"\b(?:sadece\s+)?ilk\s+(\d{1,3})\s+ay\w*\b", folded)
                if month_limit:
                    resolved_limit = int(month_limit.group(1))
            if resolved_limit and intelligence["analysis_type"] == "time_trend":
                resolved_limit = None
            # "en az / en fazla N <noun>" is an aggregate THRESHOLD ("at least N
            # appointments"), not a row count — but `_detect_limit_and_order`'s
            # ranking-count branch also grabs that same N as a TOP (N). When the
            # very same number was captured as the threshold, the row limit is
            # spurious; drop it so we don't silently cap the group list.
            if (
                aggregate_threshold is not None
                and resolved_limit is not None
                and float(resolved_limit) == aggregate_threshold.value
            ):
                resolved_limit = None
            if (
                resolved_limit is None
                and (
                    ranking
                    or intelligence["analysis_type"] in {"ranking", "top_n", "bottom_n"}
                )
                and self._singular_ranking_result_requested(folded)
            ):
                resolved_limit = 1
            # See `scalar_period_comparison` above: one row, nothing to cap.
            if scalar_period_comparison:
                resolved_limit = None

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
                limit=resolved_limit,
                percentile=percentile,
                aggregate_threshold=aggregate_threshold,
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
                assumptions=(
                    (strategy.assumptions if strategy else [])
                    + scope_assumptions
                    + self._dropped_breakdown_assumptions(intelligence)
                ),
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
            periods=self._comparison_periods(
                analysis, date_filters, signals.analysis_type, folded
            ),
            department_filter=signals.department,
            scope=scope,
            branch_filters=[],
            generic_scope_phrase_detected=generic_scope_phrase,
            extra_filters=extra_filters,
            aggregation=aggregation,
            ranking=ranking,
            limit=analysis.detected_limit,
            percentile=percentile,
            aggregate_threshold=aggregate_threshold,
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
        department_filter: str | None = None,
        department_column: str | None = None,
        status_column: str | None = None,
    ) -> dict:
        """Catalog-driven analytical resolution (Agent Intelligence Foundation).

        Deterministically resolves metrics, dimensions, analysis pattern, time
        granularity, period comparisons, derived calculations, and answerability
        from the central catalogs. Never calls an LLM.
        """
        answerable, reason, alternative = catalog.check_answerability(folded)
        metrics = catalog.match_metrics(folded)
        dimensions = catalog.match_dimensions(folded)
        # Breakdown the user asked for that this plan shape cannot honour;
        # surfaced as a plan assumption so the answer states the limitation.
        dropped_breakdown: list[str] = []
        patient_span_requested = self._patient_appointment_span_requested(folded)
        patient_period_overlap_requested = self._patient_period_overlap_requested(
            folded, analysis
        )
        if patient_span_requested:
            metrics = ["patient_appointment_span_days"]
            dimensions = [
                dimension
                for dimension in dimensions
                if self._explicit_breakdown_requested_for_dimension(folded, dimension)
            ]
            if not dimensions:
                dimensions = [
                    column
                    for column in projection
                    if self._explicit_breakdown_requested_for_dimension(folded, column)
                ]
        elif patient_period_overlap_requested:
            metrics = ["multi_period_patient_overlap_count"]
            dimensions = [
                dimension
                for dimension in dimensions
                if self._explicit_breakdown_requested_for_dimension(folded, dimension)
            ]
            if not dimensions:
                dimensions = [
                    column
                    for column in projection
                    if self._explicit_breakdown_requested_for_dimension(folded, column)
                ]

        # A named department ("Genel Cerrahi bölümünde ...") already pins
        # GenelRandevuBolumAdi to one value via department_filter; the bare
        # "bölüm(ünde)" mention that grounded it also independently matches
        # the department dimension synonym list, which would add it back as
        # a GROUP BY column too — collapsing to a single degenerate group
        # (department is already single-valued) and misclassifying the
        # analysis as a breakdown (e.g. cross_analysis/distinct_count with a
        # useless dimension) instead of a scalar/plain metric answer. Only a
        # genuine grouping marker ("bölüme göre/bazında") should keep it.
        if (
            department_filter
            and department_column
            and department_column in dimensions
            and not any(
                marker in folded for marker in ("gore", "bazinda", "bazli", "kirilim", "dagilim")
            )
        ):
            dimensions = [d for d in dimensions if d != department_column]

        # A resolved status VALUE ("... durumu gelmedi olanların ...") already
        # narrows to one status via status_value/status_filter; the bare
        # "randevu durumu" mention that grounded it also independently matches
        # the status dimension synonym list, adding it back as a degenerate
        # GROUP BY (already single-valued) - and, worse, stealing the sole
        # GROUP BY slot from the REAL grouping request elsewhere in the
        # sentence ("aylar bazında"), since DeterministicSQLBuilder._standard
        # only time-buckets when `dimensions` is empty (2026-07-27, live UI
        # testing: "... aylar bazında oranlarını ..." silently grouped by
        # status instead of by month). Unlike the department guard above (a
        # flat "any grouping marker in the sentence" check), this one must be
        # positional: the sentence CAN legitimately contain a "bazında/göre"
        # marker that belongs to a different word ("aylar"), so only a marker
        # whose captured word is itself a "durum" form keeps the dimension.
        if (
            status_value
            and status_column
            and status_column in dimensions
            and not any(
                match.group(1) in _STATUS_GROUPING_WORDS
                for match in _GROUP_BY_PATTERN.finditer(folded)
            )
        ):
            dimensions = [d for d in dimensions if d != status_column]

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
        #
        # Fires even when `metrics` is already non-empty: a phrase like
        # "randevu durumu gelmedi olanların ... oranlarını" independently
        # matches two unrelated generic metrics via bare keyword overlap
        # ("aylik randevu" -> monthly_appointment_count, "gelmedi" ->
        # no_show_count) - both real catalog synonym hits, but the WRONG
        # shape for what was actually asked (a single combined RATE, not two
        # raw counts side by side). `has_status_metric_of_kind` distinguishes
        # that from a genuinely-already-correct match (e.g. "gelmedi
        # sayısı" -> no_show_count is exactly the right count metric) so this
        # never clobbers a correct resolution (2026-07-27, live UI testing:
        # SAFE_ERROR - the resulting SQL had two raw counts and no NULLIF'd
        # division at all).
        if status_value:
            measure_kind = catalog.detect_measure_request(folded)
            if measure_kind:
                candidates = catalog.metrics_for_status_value(
                    status_value, rate=(measure_kind == "rate")
                )
                if len(candidates) == 1 and not catalog.has_status_metric_of_kind(
                    metrics, status_value, rate=(measure_kind == "rate")
                ):
                    metrics = candidates
        date_range_count = len(analysis.detected_dates)
        pattern = catalog.match_pattern(folded, date_range_count)

        # A single bare gender word ("kadin hasta orani nedir") asks for a
        # one-sided share, not a two-sided "kadin erkek orani" comparison, so
        # it never hits the CinsiyetId dimension synonym list (which requires
        # both words) and resolves NO dimension at all - unlike the two-word
        # case, the fallback below (which needs a resolved dimension) can
        # never fire for it. Ground it onto CinsiyetId directly so it shares
        # that fallback instead of producing an empty, uncomputable plan.
        # "kadin dogum" is excluded: it's the "Kadın Doğum" department name,
        # not a demographic reference.
        if (
            pattern == "ratio"
            and not metrics
            and not dimensions
            and _BARE_GENDER_TERM_PATTERN.search(folded)
            and "kadin dogum" not in folded
        ):
            dimensions = ["CinsiyetId"]

        # "X orani"/"payi" text alone pattern-matches to "ratio" even when no
        # specific ratio metric (numerator/denominator) exists for it - e.g.
        # "kadin erkek orani" has no percent-of-total metric defined, unlike
        # "gerceklesme orani" (which matches a real numerator/denominator
        # metric and is left untouched below). Without a real ratio metric,
        # "ratio" has nothing to divide; fall back to a grouped distribution
        # over the resolved dimension, or a plain count when no dimension
        # resolved either, instead of emitting a ratio plan the SQL builder
        # cannot satisfy.
        #
        # `metrics == ["appointment_count"]` (rather than "any matched
        # metric") is the deliberate signal here: appointment_count is the
        # generic volume fallback with no real ratio behind it, so this also
        # catches a channel-share question ("online randevularin payi
        # nedir") that matches only that fallback and reaches
        # PlanComplianceValidator with no NULLIF in the generated SQL ->
        # SAFE_ERROR (found via live multi-turn testing, 2026-07-24). A
        # question that instead matches a real, non-generic metric (e.g.
        # "kadin ve erkek hastalarin oranini goster" -> unique_patient_count)
        # must keep "ratio" even without a catalog numerator/denominator,
        # because app.context.analytical_signals._normalize_query_plan
        # attaches a female_to_male_ratio derived_calculation for that exact
        # shape further down the pipeline, keyed on `plan.analysis_type ==
        # "ratio"` - downgrading it here would make that enrichment's own
        # precondition never fire. A true share-of-total computation for an
        # arbitrary named value (the channel-share case) is a separate,
        # larger feature - not yet implemented.
        share_of_total_requested = (
            any(marker in folded for marker in ("pay", "payi"))
            and "toplam" in folded
            and bool(dimensions)
            and (not metrics or metrics == ["appointment_count"])
        )
        if share_of_total_requested and not metrics:
            metrics = ["appointment_count"]
        if pattern == "ratio" and (not metrics or metrics == ["appointment_count"]):
            pattern = "distribution" if dimensions else "count"

        granularity = catalog.match_granularity(folded)
        # The implied-monthly-bucket heuristic ("en çok randevu alan 3 ay")
        # must NOT fire when the turn already ranks a real entity dimension
        # (şube/bölüm/doktor): there the "ay" token belongs to a date-scope
        # phrase like "ilk 6 ayında ... en yoğun 5 şube" (= first 6 months),
        # not a request to bucket BY month. Ranking stays on the entity; a
        # spurious month grain would turn top-5-branches into top-5
        # (month, branch) rows dominated by the largest branch.
        if (
            granularity is None
            and not dimensions
            and _MONTH_BUCKET_RANKING_PATTERN.search(folded)
        ):
            granularity = "month"
        comparisons = catalog.detect_period_comparison(folded, date_range_count)
        two_month_change_request = self._can_split_two_month_span(
            analysis.detected_dates
        ) and (
            bool(self._period_change_direction(folded))
            or any(marker in folded for marker in _PERIOD_COMPARISON_MARKERS)
        )
        if two_month_change_request and not comparisons:
            comparisons = ["two_explicit_periods"]

        derived: list[str] = []
        if share_of_total_requested:
            derived.append("share_of_total: appointment_count")
        if catalog.detect_age_group_request(folded):
            derived.append(catalog.AGE_GROUP_DERIVATION)
            if "DogumTarihi" not in dimensions:
                dimensions = dimensions + ["DogumTarihi"]
        if catalog.detect_day_type_request(folded):
            derived.append(catalog.DAY_TYPE_DERIVATION)
            if _DAY_TYPE_DIMENSION not in dimensions:
                dimensions = dimensions + [_DAY_TYPE_DIMENSION]
            if metrics == []:
                metrics = ["appointment_count"]
        change_direction = self._period_change_direction(folded)
        if comparisons and change_direction:
            derived.append(f"period_change_direction:{change_direction}")

        # Structural upgrades: two grouping dimensions mean a cross analysis, a
        # time bucket means a trend, and a detected period comparison overrides
        # generic counting — regardless of which keyword triggered first.
        generic_patterns = (None, "count", "distinct_count", "distribution")
        if comparisons and pattern in generic_patterns + (
            "time_trend",
            "ranking",
            "top_n",
            "bottom_n",
        ):
            pattern = "period_comparison"
        elif granularity and pattern in generic_patterns:
            pattern = "time_trend"
        elif len(dimensions) >= 2 and pattern in generic_patterns:
            pattern = "cross_analysis"
        elif dimensions and not metrics and pattern is None:
            pattern = "distribution"
        if pattern in ("period_comparison", "percentage_change") and not comparisons:
            comparisons = ["current_period_vs_previous_period"]

        # The deterministic period-comparison SQL builder renders a single
        # row (current-period vs baseline-period totals, see
        # DeterministicSQLBuilder._period_comparison) with no GROUP BY
        # support at all — and already refuses a multi-metric plan outright
        # (falls through to the LLM path, where a dimension is still useful
        # in the prompt). A SINGLE-metric plan, though, IS handled by the
        # deterministic builder, and a dimension surviving from an
        # independent "X bazinda/gore" mention has no column to attach to in
        # that single-row shape, so PlanComplianceValidator rejects the SQL
        # as missing both the dimension and its projection column outright
        # (2026-07-24, live multi-turn testing: "2025 Mart ile 2025 Nisan
        # ayini bolum bazinda randevu sayisi olarak kiyasla" -> SAFE_ERROR;
        # the identical question without "bolum bazinda" already worked
        # correctly). A per-dimension breakdown of a period comparison is a
        # real, separate feature - not yet implemented. Clearing it here
        # (before resolved_projection is derived from `dimensions` below)
        # answers with the two-period total instead of failing outright.
        if (
            pattern == "period_comparison"
            and dimensions
            and len(metrics) <= 1
            and not patient_period_overlap_requested
        ):
            # A per-dimension breakdown of a period comparison is now built for
            # the plain VOLUME case (DeterministicSQLBuilder._period_comparison_
            # grouped: one row per department with current/baseline/diff). A
            # rate/ratio comparison still has no grouped shape, so its stray
            # dimension is dropped to keep the two-period scalar answerable.
            # `metrics` here is still the pre-ratio guess (numerator/denominator
            # are derived below), so gate on the count metric directly.
            supported_grouped = metrics in ([], ["appointment_count"])
            if not supported_grouped:
                # Record what was dropped so the answer can SAY the breakdown
                # was not applied. Silently returning a two-period total for
                # "bölüm bazında kıyasla" reads as a wrong answer rather than a
                # limitation (Codex live UI finding, 2026-07-31).
                dropped_breakdown = [
                    get_dimension_label(dimension) for dimension in dimensions
                ]
                dimensions = []

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
            if primary.analysis_type == "repeat_behavior" and (
                primary.formula_type.startswith("having_")
                or primary.formula_type
                in {"patient_span_days", "period_overlap_distinct_count"}
            ):
                pattern = primary.analysis_type
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
            # A scalar self-averaging metric ("günlük ortalama randevu sayısı" ->
            # daily_average_appointment_count) already divides by the distinct
            # bucket count in its own formula, so it must stay a single row. The
            # bucket WORD ("günlük") that also matched `match_granularity` would
            # otherwise GROUP BY day, collapsing each group to one date and
            # turning the average into that day's raw count. The metric's own
            # declared granularity (None here) is authoritative for such metrics.
            if primary.analysis_type == "average" and not primary.grouping_granularity:
                granularity = None
            if primary.fixed_dimension and primary.fixed_dimension not in dimensions:
                dimensions = dimensions + [primary.fixed_dimension]

        explicit_self_breakdown = any(
            marker in folded
            for marker in (
                "hasta bazinda",
                "hastaya gore",
                "hasta id",
                "hasta kimligi",
                "doktor id",
                "doktor bazinda doktor",
            )
        )
        if not explicit_self_breakdown:
            self_count_columns: set[str] = set()
            for metric_id in metrics:
                metric = by_id.get(metric_id)
                if metric is None or metric.formula_type != "count_distinct":
                    continue
                self_count_columns.update(metric.required_columns)
                self_count_columns.update(_SELF_COUNT_DIMENSIONS.get(metric.id, set()))
            if self_count_columns:
                dimensions = [d for d in dimensions if d not in self_count_columns]

        relationship_condition_columns: set[str] = set()
        for metric_id in metrics:
            relationship_condition_columns.update(
                _RELATIONSHIP_CONDITION_DIMENSIONS.get(metric_id, set())
            )
        if relationship_condition_columns:
            dimensions = [
                dimension
                for dimension in dimensions
                if dimension not in relationship_condition_columns
                or self._explicit_breakdown_requested_for_dimension(folded, dimension)
            ]

        if pattern == "cross_analysis" and len(dimensions) < 2:
            pattern = "distribution" if dimensions else "count"

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
        ):
            self_columns = set(primary.required_columns) | _SELF_COUNT_DIMENSIONS.get(
                primary.id, set()
            )
            if not explicit_self_breakdown:
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
            "dropped_breakdown": dropped_breakdown,
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
        if re.search(
            r"\bilk\s+\d+\s+(?:doktor|hekim|hizmet|servis|sube|bolum|kaynak|kategori|yas)",
            folded_question,
        ):
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
        if any(
            marker in folded_question
            for marker in ("gore", "bazinda", "dagilim", "oran", "kirilim")
        ):
            return False
        if any(
            marker in folded_question
            for marker in ("trend", "egilim", "aylik", "gunluk", "haftalik")
        ):
            return False
        if "randevu" in folded_question:
            return True
        return bool(analysis.detected_limit)

    def _singular_ranking_result_requested(self, folded_question: str) -> bool:
        if re.search(r"\b(?:hangileri|kimler)\b", folded_question):
            return False
        return bool(re.search(r"\b(?:hangisi|kim)\b", folded_question))

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

    def _patient_appointment_span_requested(self, folded_question: str) -> bool:
        """Detect patient first-to-last appointment span requests."""
        has_patient = re.search(r"\bhasta\w*\b", folded_question) is not None
        first_last = (
            re.search(r"\bilk\w*\b", folded_question) is not None
            and re.search(r"\bson\w*\b", folded_question) is not None
            and "randevu" in folded_question
        )
        span_wording = (
            "gun fark" in folded_question
            or "kac gun gec" in folded_question
            or "arasinda kac gun" in folded_question
            or "en yuksek fark" in folded_question
            or "ortalama gun fark" in folded_question
        )
        return bool((has_patient and first_last) or (has_patient and span_wording))

    def _patient_period_overlap_requested(
        self, folded_question: str, analysis: QueryAnalysis
    ) -> bool:
        """Detect patients present in both explicit periods."""
        if len(analysis.detected_dates) < 2:
            return False
        has_patient = re.search(r"\bhasta\w*\b", folded_question) is not None
        has_overlap_marker = (
            re.search(r"\bhem\b.+\bhem\b", folded_question) is not None
            or "her iki" in folded_question
            or "iki donemde" in folded_question
            or "iki yilda" in folded_question
            or "ortak hasta" in folded_question
        )
        has_presence_action = any(
            marker in folded_question
            for marker in ("islem goren", "randevusu olan", "gelen", "say")
        )
        return bool(has_patient and has_overlap_marker and has_presence_action)

    def _explicit_breakdown_requested_for_dimension(
        self, folded_question: str, dimension: str
    ) -> bool:
        dimension_terms = {
            "HizmetAdi": ("hizmet", "servis"),
            "SubeAdi": ("sube", "merkez", "lokasyon"),
            "GenelRandevuBolumAdi": ("bolum", "brans"),
            "GenelRandevuKaynakAdi": ("kaynak", "kanal"),
            "DoktorId": ("doktor", "hekim"),
            "RandevuDurumu": ("durum", "status"),
            "CinsiyetId": ("cinsiyet",),
        }
        terms = dimension_terms.get(dimension, (dimension.lower(),))
        for term in terms:
            if re.search(
                rf"\b{term}\w*\s+(?:baz\w*|gore|dagilim\w*|kirilim\w*|kir\w*|sirala\w*)\b",
                folded_question,
            ):
                return True
            if re.search(
                rf"\b(?:dagilim\w*|kirilim\w*|kir\w*)\s+{term}\w*\b",
                folded_question,
            ):
                return True
        return False

    def _fuzzy_group_dimension(self, folded_question: str, view_name: str) -> str | None:
        """Recovers a grouping dimension from a single-char TYPO in the grouping
        word ("bolm bazında", "doktr bazında") — used ONLY as a last resort when
        the exact catalog/concept matchers found no dimension at all, so it never
        overrides a deliberate no-dimension decision. Matches by one insertion/
        deletion against the concept vocabulary; substitutions are NOT tolerated
        (they collide too easily, e.g. süre↔şube). The grammatical grouping
        position keeps this low-risk (robustness probe round 4, 2026-07-29)."""
        concepts = view_mapping.get_view_entry(view_name).get("concepts", {})
        fuzzy_column: str | None = None
        for match in _GROUP_BY_PATTERN.finditer(folded_question):
            word = match.group(1)
            if len(word) < 4:
                continue
            for spec in concepts.values():
                column = spec.get("column")
                if not column or column.lower().endswith("id"):
                    continue
                for term in spec.get("terms", []):
                    folded_term = view_mapping.fold(term)
                    if " " in folded_term or len(folded_term) < 4:
                        continue
                    if word.startswith(folded_term):
                        return None  # an exact match exists anywhere — not a typo
                    if fuzzy_column is None and self._one_indel_apart(word, folded_term):
                        fuzzy_column = column
        return fuzzy_column

    @staticmethod
    def _one_indel_apart(a: str, b: str) -> bool:
        """True when `a` and `b` differ by exactly one inserted/deleted char.

        Length-1 apart only (no substitutions) — catches the common
        missing/extra-letter typo without the false matches a substitution
        distance would allow among short, similar concept words.
        """
        short, long = (a, b) if len(a) < len(b) else (b, a)
        if len(long) - len(short) != 1:
            return False
        i = j = 0
        skipped = False
        while i < len(short) and j < len(long):
            if short[i] == long[j]:
                i += 1
                j += 1
            elif skipped:
                return False
            else:
                skipped = True
                j += 1
        return True

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
        folded: str,
    ) -> list[PeriodPlan]:
        """Carries parser periods into the plan as half-open ranges.

        Periods are ordered [baseline, current] — the invariant the SQL builder
        and comparison renderer rely on. For a *symmetric* comparison ("A ile B",
        "A ve B") the parser's mention order is kept as-is (first mentioned =
        baseline). For a *directional* comparison naming a reference period
        ("2025'in 2024'e göre değişimi") the first-mentioned period is the
        subject/current and the second is the baseline, so we reverse mention
        order to restore the [baseline, current] invariant.
        """
        if analysis_type in _PERIOD_ANALYSIS_TYPES:
            split_span_periods = self._two_month_span_periods(
                analysis.detected_dates,
                date_filters,
            )
            if split_span_periods:
                return split_span_periods
        if analysis_type not in _PERIOD_ANALYSIS_TYPES or len(analysis.detected_dates) < 2:
            return []

        periods: list[PeriodPlan] = []
        # A follow-up resolves to the PREVIOUS question prepended to the current
        # one ("2024 ve 2025 ... karşılaştır. 2025, 2024'e göre ..."), so each
        # year is detected twice and the comparison would carry the same window
        # two or four times — a self-comparison the compliance guard rejects,
        # surfacing as "Yanıt Oluşturulamadı" on the most natural follow-up
        # there is (Codex live UI testing, 2026-07-31). Keep first occurrence.
        seen: set[tuple[str, str]] = set()
        for detected, date_filter in zip(analysis.detected_dates, date_filters, strict=True):
            start = detected.start_date.isoformat()
            end = (detected.end_date + timedelta(days=1)).isoformat()
            if (start, end) in seen:
                continue
            seen.add((start, end))
            periods.append(
                PeriodPlan(
                    label=self._period_label(detected),
                    start_inclusive=start,
                    end_exclusive=end,
                    column=date_filter.column,
                )
            )
        if len(periods) == 2:
            reference = catalog.directional_reference_token(folded)
            if reference:
                # [baseline, current]: the period named as the REFERENCE ("…'e
                # göre") is the baseline, whichever order the text mentions
                # them in. Falls back to leaving the order alone when the token
                # matches neither label, so an unrecognised form can never
                # silently invert the comparison.
                folded_labels = [self._extractor.fold(period.label) for period in periods]
                if reference in folded_labels[1] and reference not in folded_labels[0]:
                    periods.reverse()
        return periods

    def _dropped_breakdown_assumptions(self, intelligence: dict) -> list[str]:
        """States a breakdown the plan could not honour, so the answer does not
        present a two-period total as if it were the requested per-dimension
        comparison."""
        dropped = intelligence.get("dropped_breakdown") or []
        if not dropped:
            return []
        return [
            f"{', '.join(dropped)} bazında dönem karşılaştırması bu metrik için "
            "henüz desteklenmiyor; sonuç dönem toplamları olarak verildi."
        ]

    def _period_change_direction(self, folded_question: str) -> str | None:
        return catalog.period_change_direction(folded_question)

    def _can_split_two_month_span(self, detected_dates: list) -> bool:
        return bool(self._two_month_span_periods(detected_dates, []))

    def _two_month_span_periods(
        self,
        detected_dates: list,
        date_filters: list[DateFilterPlan],
    ) -> list[PeriodPlan]:
        if len(detected_dates) != 1:
            return []
        detected = detected_dates[0]
        start = detected.start_date
        end = detected.end_date
        if start.day != 1:
            return []
        start_index = start.year * 12 + start.month
        end_index = end.year * 12 + end.month
        if end_index - start_index != 1:
            return []
        first_exclusive = self._next_month_start(start.year, start.month)
        second_exclusive = self._next_month_start(end.year, end.month)
        if end != second_exclusive - timedelta(days=1):
            return []
        column = date_filters[0].column if date_filters else None
        return [
            PeriodPlan(
                label=f"{_MONTH_LABELS[start.month]} {start.year}",
                start_inclusive=start.isoformat(),
                end_exclusive=first_exclusive.isoformat(),
                column=column,
            ),
            PeriodPlan(
                label=f"{_MONTH_LABELS[end.month]} {end.year}",
                start_inclusive=end.replace(day=1).isoformat(),
                end_exclusive=second_exclusive.isoformat(),
                column=column,
            ),
        ]

    def _next_month_start(self, year: int, month: int):
        if month == 12:
            return date(year + 1, 1, 1)
        return date(year, month + 1, 1)

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
        # A full calendar year labels as just the year. The raw expression can
        # carry trailing preposition/question words ("2025 için", "2024 yılına",
        # "2023 yılında") the parser kept attached to the date token — those must
        # never leak into the period label (or the SQL N'...' literal and the
        # user-facing "… döneminde" summary). Extract the year instead of
        # requiring the whole expression to be exactly four digits.
        if period.granularity == "year":
            year_match = re.search(r"\b(\d{4})\b", period.expression)
            if year_match:
                return year_match.group(1)
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
        explicit_direction = self._explicit_sort_direction(folded_question)
        if explicit_direction is not None:
            return explicit_direction, explicit_direction
        if analysis_type == "ranking":
            direction = (
                "ASC" if any(marker in folded_question for marker in _ASCENDING_MARKERS) else "DESC"
            )
            return direction, order
        return (order, order) if order else (None, None)

    def _explicit_sort_direction(self, folded_question: str) -> str | None:
        if "sirala" not in folded_question and "siralay" not in folded_question:
            return None
        if any(marker in folded_question for marker in _ORDER_ASC_MARKERS):
            return "ASC"
        if any(marker in folded_question for marker in _ORDER_DESC_MARKERS):
            return "DESC"
        return "DESC"

    # Strong interrogatives — each marks an INDEPENDENT question. Requiring one
    # on BOTH sides of "ve"/"ayrıca" is what separates a genuine compound
    # question ("toplam kaç randevu var VE en yoğun ay hangisiydi") from a mere
    # coordinated noun phrase ("hafta içi ve hafta sonu", "kadın ve erkek",
    # "Kadın Doğum ve Çocuk Sağlığı") — those carry no question word per side.
    _COMPOUND_QUESTION_WORDS = (
        "kac ",
        "kaci",
        "hangi",
        "hangisi",
        "nedir",
        "ne kadar",
        "kim ",
        "kimin",
        "kimdir",
        "en yogun",
        "en cok",
        "en fazla",
        "en yuksek",
        "en dusuk",
        "en az",
    )

    def _compound_secondary_clause(self, question: str, folded_question: str) -> str | None:
        """Detects a two-part compound question and returns the secondary clause.

        The planner produces exactly one QueryPlan, so a compound question
        ("toplam kaç randevu var ve en yoğun ay hangisiydi") is answered only
        for its first clause. Rather than silently drop the rest, return the
        second question-bearing clause so the caller can state it was not
        answered. Conservative by design: a clause counts only if it carries a
        strong interrogative of its own, so coordinated noun phrases joined by
        "ve" never trip it.
        """
        raw_parts = re.split(r"\s+(?:ve|ayrica|ayrıca)\s+", question, flags=re.IGNORECASE)
        if len(raw_parts) < 2:
            return None
        question_parts = [
            part.strip()
            for part in raw_parts
            if any(word in self._extractor.fold(part) for word in self._COMPOUND_QUESTION_WORDS)
        ]
        if len(question_parts) < 2:
            return None
        return question_parts[1]

    def _percentile(self, question: str, folded_question: str) -> int | None:
        """Detects a top/bottom percentile slice ("en üstteki %10'u göster").

        The "%" sign is stripped by both normalization AND folding, so a "%N"
        percentile is indistinguishable from a plain count once folded (and its
        N is even misread as a TOP (N) row limit). Detect it from the RAW
        question, where "%" survives; "yüzde N" (spelled) is caught on the
        folded text. Only a top/bottom RANKING context qualifies, so a ratio
        value ("gelmeme oranı %10") never triggers a percentile slice.
        """
        match = re.search(r"%\s*(\d{1,3})", question)
        if match is None:
            match = re.search(r"\byuzde\s+(\d{1,3})\b", folded_question)
        if match is None:
            return None
        value = int(match.group(1))
        if not 1 <= value <= 99:
            return None
        ranking_context = (
            "en ustteki",
            "en alttaki",
            "ustteki",
            "alttaki",
            "en yuksek",
            "en dusuk",
            "en cok",
            "en fazla",
            "dilim",
            "luk",
            "lik",
        )
        if not any(marker in folded_question for marker in ranking_context):
            return None
        return value

    _AGE_EXPR = "DATEDIFF(year, DogumTarihi, GETDATE())"

    def _age_filter(self, folded_question: str) -> str | None:
        """Extracts an age-RANGE WHERE predicate ("40 yaş üstü", "18 yaşından
        küçük", "30-40 yaş arası", "65 yaş ve üzeri"). Age is derived from
        DogumTarihi the same way the age-group bucket is. Returns a T-SQL
        predicate string, or None when the question carries no age bound.
        """
        # "30-40 yaş arası" / "30 40 yaş arası" — an inclusive band.
        band = re.search(
            r"\b(\d{1,3})\s*[-\s]\s*(\d{1,3})\s+yas\w*\s+aras", folded_question
        )
        if band:
            low, high = sorted((int(band.group(1)), int(band.group(2))))
            return f"{self._AGE_EXPR} BETWEEN {low} AND {high}"
        # "N yaş ve üzeri/üstü" — inclusive lower bound (>=).
        at_least = re.search(
            r"\b(\d{1,3})\s+yas\w*\s+ve\s+(?:uzeri|ustu|yukari)", folded_question
        )
        if at_least:
            return f"{self._AGE_EXPR} >= {int(at_least.group(1))}"
        # "N yaş üstü/üzeri/üzerinde/büyük" — strict lower bound (>).
        above = re.search(
            r"\b(\d{1,3})\s+yas\w*\s+(?:ustu|uzeri|uzerinde|buyuk|yukari)", folded_question
        )
        if above:
            return f"{self._AGE_EXPR} > {int(above.group(1))}"
        # "N yaşından küçük / N yaş altı / N yaşından az" — strict upper bound (<).
        below = re.search(
            r"\b(\d{1,3})\s+yas\w*\s+(?:kucuk|alti|az|asagi)", folded_question
        )
        if below:
            return f"{self._AGE_EXPR} < {int(below.group(1))}"
        return None

    def _aggregate_threshold(self, folded_question: str) -> AggregateThreshold | None:
        """Extracts a HAVING-style bound on the grouped aggregate value.

        "200'den az / 500'den fazla / 100'ün altında / 1000'in üzerinde
        randevusu olan bölümler" — a filter on the aggregate COUNT/SUM/AVG per
        group, distinct from a row LIMIT ("ilk 5") or a ranking direction. The
        builder only renders it when the plan actually groups by a dimension;
        without a GROUP BY there is no aggregate to bound.
        """
        # Number token that tolerates a Turkish thousands separator. Normalization
        # turns "1.000" into "1 000" (the dot becomes a space), so a bare
        # `\d[\d.]*` would capture only the trailing "000" next to "den" and read
        # 1.000 as 0 (robustness probe round 7, 2026-07-29). The first
        # alternative requires a 1-3 digit lead + at least one space/dot + 3-digit
        # group (so a real "1 000" joins but a "2024 500" year+threshold pair does
        # NOT — 2024 is 4 digits, an impossible thousands lead); a plain
        # unseparated number falls through to `\d+`.
        num = r"(\d{1,3}(?:[ .]\d{3})+|\d+)"
        # "N'den az/küçük", "N'den fazla/çok/büyük" — the apostrophe/suffix
        # ('den/'dan/den/dan) is normalized away, so match an optional gap.
        # The POSITIONAL words take Turkish relative suffixes in everyday
        # phrasing — "1000 altındaki hekimler", "500 üzerindeki bölümler",
        # "100 altındakileri" — so they need a trailing `\w*`. Without it only
        # the bare "altında"/"üzerinde" forms matched and a very common request
        # produced no threshold at all (Codex live UI testing, 2026-07-31:
        # "1000 altındaki hekimleri ele" applied no filter). The COMPARATIVE
        # words stay anchored: a `\w*` on "az" would swallow "azalan" (a sort
        # direction) and on "cok" would swallow "coklu".
        less = re.search(
            rf"\b{num}\s*(?:'?d[ae]n|'?nin|'?in|'?un|'?nun)?\s*"
            r"(az|kucuk|kucugu|asagi|alt(?:i|inda)\w*)\b",
            folded_question,
        )
        more = re.search(
            rf"\b{num}\s*(?:'?d[ae]n|'?nin|'?in|'?un|'?nun)?\s*"
            r"(fazla|cok|buyuk|buyugu|ust(?:u|unde)\w*|uzer(?:i|inde)\w*)\b",
            folded_question,
        )
        # "en az N" / "en fazla N" — inclusive bounds ("at least/at most N").
        at_least = re.search(rf"\ben\s+az\s+{num}\b", folded_question)
        at_most = re.search(rf"\ben\s+(?:cok|fazla)\s+{num}\b", folded_question)

        def _num(token: str) -> float | None:
            cleaned = token.replace(".", "").replace(" ", "")
            return float(cleaned) if cleaned.isdigit() else None

        # An exclusion phrase flips the bound: "100'den az olanları DIŞARIDA
        # BIRAK / hariç tut / çıkar" keeps the complement (>= 100), not the
        # matched "< 100" set. Without this the filter kept exactly the groups
        # the user asked to remove (Codex live UI finding). "hariç" for a named
        # department has no numeric bound here, so it never reaches this branch.
        excludes = any(
            marker in folded_question
            for marker in ("disarida birak", "disari birak", "haric tut", "haricinde", "cikar")
        ) or bool(_ELIMINATE_MARKER.search(folded_question))
        inverse = {">=": "<", "<=": ">", "<": ">=", ">": "<="}

        def _bound(operator: str, token: str) -> AggregateThreshold | None:
            value = _num(token)
            if value is None:
                return None
            resolved = inverse[operator] if excludes else operator
            return AggregateThreshold(operator=resolved, value=value)

        if at_least:
            return _bound(">=", at_least.group(1))
        if at_most:
            return _bound("<=", at_most.group(1))
        if less:
            return _bound("<", less.group(1))
        if more:
            return _bound(">", more.group(1))
        return None

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
        roles = ("baseline", "current") if len(plan.periods) == 2 else ()
        for index, period in enumerate(plan.periods, start=1):
            role = roles[index - 1] if roles else f"period {index}"
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
    if plan.aggregate_threshold is not None:
        threshold = plan.aggregate_threshold
        lines.append(
            f"- Aggregate threshold: keep only groups whose aggregate "
            f"{threshold.operator} {threshold.value:g} (T-SQL: HAVING on the aggregate, "
            f"never a WHERE row filter)"
        )
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
