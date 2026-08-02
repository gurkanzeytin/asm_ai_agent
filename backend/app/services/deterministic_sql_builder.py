"""Deterministic SQL generation from QueryPlan.

This builder covers catalog-backed analytical plans for the SQL Server
appointment reporting view. It intentionally returns unsupported for plans that
need schema invention or unverified metric mappings; SQLService can then use
the existing LLM fallback path.
"""

# ruff: noqa: E501

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.database_intelligence.value_catalog import FIELD_COLUMNS
from app.planning.models import InlineMetric, MetricPredicate, QueryPlan
from app.semantics.catalog import (
    AGE_GROUP_DERIVATION,
    DAY_TYPE_DERIVATION,
    load_column_catalog,
    load_metric_catalog,
)
from app.semantics.view_mapping import fold

SUPPORTED_ANALYSIS_TYPES = {
    "count",
    "distinct_count",
    "distribution",
    "ranking",
    "top_n",
    "bottom_n",
    "ratio",
    "percentage",
    "conversion",
    "average",
    "minimum",
    "maximum",
    "time_trend",
    "period_comparison",
    "baseline_comparison",
    "cohort_analysis",
    "anomaly_comparison",
    "variance_analysis",
    "cross_analysis",
    "data_quality",
    "duration_analysis",
    "lead_time_analysis",
    "repeat_behavior",
    "list",
    "adaptive_time_comparison",
    "percentage_change",
    "comparison",
    "multi_metric_performance",
}

VIEW = "dbo.vw_RandevuRaporu"

# Verified live RandevuDurumu values (2026-07). 'İptal' does NOT exist in the
# data; no builder path may generate a cancelled metric or an İptal literal.
VERIFIED_STATUS_VALUES = {
    "completed": "Gerçekleşti",
    "checked_in": "Giriş Yapılmış",
    "no_show": "Gelmedi",
    "in_progress": "İşlem Sürmekte",
    "waiting": "Beklemede",
}
DATE_COLUMN = "BaslangicTarihi"
# GenelRandevuBolumAdi stores comma-separated composites ("Genel Cerrahi,
# Ameliyathane, "); equality on the raw value never matches a single
# department, so its predicates are rendered as delimiter-bounded containment.
DEPARTMENT_COLUMN = "GenelRandevuBolumAdi"
# Used by `_can_condition` to tell a single-aggregate metric formula (safe to
# gate on a period) from a composite rate formula (two aggregates + arithmetic,
# which cannot be wrapped without nesting aggregates).
_AGGREGATE_CALL = re.compile(r"\b(?:COUNT|SUM|AVG|MIN|MAX)\s*\(", re.IGNORECASE)
_LEADING_AGGREGATE = re.compile(r"\s*(?:COUNT|SUM|AVG|MIN|MAX)\s*\(", re.IGNORECASE)
# Table alias for the CROSS APPLY STRING_SPLIT that explodes the composite
# department column into one atomic value per row (see `_standard`).
_DEPARTMENT_SPLIT_ALIAS = "dept_atomic"
# Operators a plan-composed `MetricPredicate` may render. An allow-list, not a
# sanitiser: anything outside it makes the metric unrenderable rather than
# being escaped into SQL.
_PREDICATE_OPERATORS = frozenset({"=", "<>", ">", ">=", "<", "<=", "IS NULL", "IS NOT NULL"})
# "Yaş gruplarına göre ..." groups by decade, never the raw birth date - kept
# identical to catalog.AGE_GROUP_DERIVATION's documented formula (see
# `_standard`) so the two never drift apart.
_AGE_GROUP_COLUMN = "DogumTarihi"
_AGE_GROUP_EXPR = f"(DATEDIFF(year, {_AGE_GROUP_COLUMN}, GETDATE()) / 10) * 10"
# Sentinel dimension for the weekday/weekend breakdown (catalog.DAY_TYPE_
# DERIVATION). Not a real column — rendered from the plan's date column via a
# DATEFIRST/locale-independent CASE (Mon=0..Sun=6, >= 5 == weekend).
_DAY_TYPE_COLUMN = "DayType"
FILTER_COLUMNS = {
    *(column for column, _tier in FIELD_COLUMNS.values()),
    "DoktorId",
}
_SIMPLE_FILTER = re.compile(
    r"^\s*\[?(?P<column>[A-Za-z_][A-Za-z0-9_]*)\]?\s*=\s*"
    r"(?:(?:N)?'(?P<text>(?:''|[^'])*)'|(?P<number>-?\d+(?:\.\d+)?))\s*$",
    re.IGNORECASE,
)
LAST_30 = f"{DATE_COLUMN} >= DATEADD(day, -30, CAST(GETDATE() AS date)) AND {DATE_COLUMN} < DATEADD(day, 1, CAST(GETDATE() AS date))"
PREVIOUS_30 = f"{DATE_COLUMN} >= DATEADD(day, -60, CAST(GETDATE() AS date)) AND {DATE_COLUMN} < DATEADD(day, -30, CAST(GETDATE() AS date))"
LAST_90 = f"{DATE_COLUMN} >= DATEADD(day, -90, CAST(GETDATE() AS date)) AND {DATE_COLUMN} < DATEADD(day, 1, CAST(GETDATE() AS date))"
PREVIOUS_90 = f"{DATE_COLUMN} >= DATEADD(day, -180, CAST(GETDATE() AS date)) AND {DATE_COLUMN} < DATEADD(day, -90, CAST(GETDATE() AS date))"


@dataclass(frozen=True)
class DeterministicSQL:
    sql: str
    result_schema: str
    expected_aliases: list[str]
    skipped_metrics: list[str] = field(default_factory=list)
    metric_aliases: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class UnsupportedPlan:
    reason: str
    skipped_metrics: list[str] = field(default_factory=list)


class DeterministicSQLBuilder:
    """Builds SQL Server SELECT statements for supported QueryPlan shapes."""

    def __init__(self) -> None:
        self._metric_catalog = load_metric_catalog()
        self._metrics = self._metric_catalog.by_id()

    def build(
        self, plan: QueryPlan, *, adaptive_retry: bool = False
    ) -> DeterministicSQL | UnsupportedPlan:
        if not plan.answerable:
            return UnsupportedPlan(plan.answerability_reason or "plan is marked unanswerable")
        # A generic negation ("uyruğu Türkiye OLMAYAN", "randevusu BULUNMAYAN")
        # is carried as an unstructured planner HINT ("NEGATION: exclude ...")
        # meant for the LLM, not a real T-SQL predicate. The deterministic
        # builder cannot render it (it has no grounded target column/value), so
        # routing it here previously leaked the literal hint into the WHERE
        # clause and crashed the query (live 2026-07-28). Hand these plans to
        # the LLM path, which reads the hint and renders a NOT EXISTS/<> filter.
        if any(extra.strip().upper().startswith("NEGATION:") for extra in plan.extra_filters):
            return UnsupportedPlan("unstructured negation hint requires LLM rendering")
        analysis_type = self._analysis_type(plan)
        if analysis_type not in SUPPORTED_ANALYSIS_TYPES:
            return UnsupportedPlan(f"unsupported analysis type: {analysis_type}")
        if analysis_type == "cohort_analysis":
            return self._cohort(plan, adaptive_retry=adaptive_retry)
        if analysis_type in {
            "period_comparison",
            "baseline_comparison",
            "adaptive_time_comparison",
            "percentage_change",
            "multi_metric_performance",
        }:
            return self._period_comparison(plan, adaptive_retry=adaptive_retry)
        if analysis_type == "comparison":
            if plan.periods or len(plan.date_filters) >= 2:
                return self._period_comparison(plan, adaptive_retry=adaptive_retry)
            return self._entity_comparison(plan)
        if analysis_type == "anomaly_comparison":
            return self._anomaly(plan, adaptive_retry=adaptive_retry)
        if analysis_type == "variance_analysis":
            return self._variance(plan)
        if analysis_type == "time_trend":
            if plan.dimensions or len(self._metric_ids(plan, "time_trend")) > 1:
                return self._standard(plan, analysis_type)
            return self._trend(plan)
        if analysis_type == "list":
            return self._list(plan)
        if analysis_type == "repeat_behavior":
            repeat_sql = self._repeat_behavior(plan)
            if repeat_sql is not None:
                return repeat_sql
        return self._standard(plan, analysis_type)

    def metric_sql_map(self) -> dict[str, str]:
        return {
            metric.id: metric.formula
            for metric in self._metric_catalog.metrics
            if metric.formula and metric.status != "requires_verified_mapping"
        }

    def _analysis_type(self, plan: QueryPlan) -> str:
        if plan.analysis_type:
            return plan.analysis_type
        if plan.numerator and plan.denominator:
            return "ratio"
        if plan.aggregation:
            return "count" if "count" in plan.aggregation.lower() else plan.aggregation.lower()
        return "count"

    def _standard(self, plan: QueryPlan, analysis_type: str) -> DeterministicSQL | UnsupportedPlan:
        metric_ids = self._metric_ids(plan, analysis_type)
        metric_exprs, skipped = self._metric_expressions(metric_ids, plan.metric_specs)
        if not metric_exprs:
            return UnsupportedPlan("no verified metric mapping", skipped)

        dimensions = self._dimensions(plan)
        if analysis_type == "data_quality" and metric_ids:
            # "Bölüm bilgisi boş kayıtlar" names the field being checked, not
            # a useful GROUP BY: every matching value is NULL. Keep genuine
            # external breakdowns ("şube bazında eksik doktor") while dropping
            # only dimensions owned by the measured quality rule itself.
            primary_spec = self._metrics.get(metric_ids[0])
            if primary_spec is not None:
                dimensions = [
                    dimension
                    for dimension in dimensions
                    if dimension not in primary_spec.required_columns
                ]
        time_bucket_expr = None
        if plan.grouping_granularity:
            date_column = (
                plan.date_filters[0].column if plan.date_filters else None
            ) or DATE_COLUMN
            time_bucket_expr = self._time_bucket_expression(plan.grouping_granularity, date_column)
        splits_department = DEPARTMENT_COLUMN in dimensions
        # GenelRandevuBolumAdi is comma-separated composite text ("Genel
        # Cerrahi, Ameliyathane, "). Grouping the raw column yields one row
        # per distinct COMBINATION (425+ of them) instead of one row per
        # atomic department - a "top/bottom N bölüm" question then returns
        # nonsense like "Nöroşirurji, Plastik ve Rekonstruktif Cerrahi," as
        # if it were a single department (2026-07-27, live multi-turn
        # testing). `_department_split_cross_apply` explodes each row into
        # one per atomic department first, the same way filters already do
        # via `_department_containment` - a row belonging to two departments
        # is correctly counted under both.
        # "Yaş gruplarına göre ... göster" - the planner adds DogumTarihi to
        # `dimensions` and a human-readable note to `derived_calculations`
        # (catalog.AGE_GROUP_DERIVATION: "10'luk yaş grupları"), but nothing
        # ever consumed that note - GROUP BY grouped the raw birth date
        # itself, one row per distinct date (up to 1000) instead of one row
        # per decade bucket (2026-07-27, live multi-turn testing). Rendering
        # the SAME bucketing formula the derivation note already describes.
        # Gated on that SAME note (not merely "DogumTarihi is a dimension"):
        # "doğum tarihine göre hasta dağılımı" legitimately asks to group by
        # the raw birth date itself, with no age-group derivation attached -
        # bucketing it too would answer a different question than asked.
        buckets_age = (
            _AGE_GROUP_COLUMN in dimensions and AGE_GROUP_DERIVATION in plan.derived_calculations
        )
        buckets_day_type = (
            _DAY_TYPE_COLUMN in dimensions and DAY_TYPE_DERIVATION in plan.derived_calculations
        )
        output_alias_for = {DEPARTMENT_COLUMN: DEPARTMENT_COLUMN}
        group_expr_for = {DEPARTMENT_COLUMN: f"{_DEPARTMENT_SPLIT_ALIAS}.value"}
        if buckets_age:
            output_alias_for[_AGE_GROUP_COLUMN] = "age_group"
            group_expr_for[_AGE_GROUP_COLUMN] = _AGE_GROUP_EXPR
        if buckets_day_type:
            day_type_column = (
                plan.date_filters[0].column if plan.date_filters else None
            ) or DATE_COLUMN
            output_alias_for[_DAY_TYPE_COLUMN] = "day_type"
            group_expr_for[_DAY_TYPE_COLUMN] = (
                f"CASE WHEN DATEDIFF(day, '19000101', {day_type_column}) % 7 >= 5 "
                f"THEN N'Hafta Sonu' ELSE N'Hafta İçi' END"
            )
        select_parts = [f"{time_bucket_expr} AS period_start"] if time_bucket_expr else []
        group_by_columns = [time_bucket_expr] if time_bucket_expr else []
        expected_aliases = ["period_start"] if time_bucket_expr else []
        select_parts.extend(
            [
                f"{group_expr_for[dimension]} AS {output_alias_for[dimension]}"
                if dimension in group_expr_for
                else f"{dimension} AS {dimension}"
                for dimension in dimensions
            ]
        )
        group_by_columns.extend(
            group_expr_for.get(dimension, dimension) for dimension in dimensions
        )
        expected_aliases.extend(
            output_alias_for.get(dimension, dimension) for dimension in dimensions
        )
        metric_aliases: dict[str, str] = {}
        primary_metric_alias = ""
        primary_metric_expression = metric_exprs[0][1]
        for metric_id, expression in metric_exprs:
            alias = self._alias_for_metric(metric_id, analysis_type)
            select_parts.append(f"{expression} AS {alias}")
            expected_aliases.append(alias)
            metric_aliases[metric_id] = alias
            if not primary_metric_alias:
                primary_metric_alias = alias
        if self._has_share_of_total(plan) and group_by_columns:
            select_parts.append(
                f"100.0 * {primary_metric_expression} / NULLIF(SUM({primary_metric_expression}) OVER (), 0) "
                "AS pay_yuzdesi"
            )
            expected_aliases.append("pay_yuzdesi")
        where = self._where(plan)
        # Department EXCLUSION ("Kardiyoloji hariç ..."). When the query splits
        # the composite department column, exclude the ATOMIC value so a
        # composite row ("Kardiyoloji, Nöroloji") still contributes its OTHER
        # departments; otherwise exclude at the row level via NOT-containment.
        if plan.excluded_departments and not splits_department:
            row_exclusion = f"NOT ({self._department_containment(plan.excluded_departments)})"
            where = (
                f"{where.rstrip()} AND {row_exclusion}\n" if where else f"WHERE {row_exclusion}\n"
            )
        if splits_department:
            empty_guard = f"{_DEPARTMENT_SPLIT_ALIAS}.value <> ''"
            atomic_department_guard = self._atomic_department_guard(
                self._department_filter_values(plan)
            )
            if atomic_department_guard:
                empty_guard = f"{empty_guard} AND {atomic_department_guard}"
            if plan.excluded_departments:
                literals = ", ".join(
                    self._unicode_literal(value) for value in plan.excluded_departments
                )
                empty_guard = (
                    f"{empty_guard} AND {_DEPARTMENT_SPLIT_ALIAS}.value NOT IN ({literals})"
                )
            where = f"{where.rstrip()} AND {empty_guard}\n" if where else f"WHERE {empty_guard}\n"
        from_clause = f"FROM {VIEW}\n"
        if splits_department:
            from_clause += self._department_split_cross_apply()
        group_by = f"\nGROUP BY {', '.join(group_by_columns)}" if group_by_columns else ""
        having = self._having(plan, group_by_columns, metric_exprs)
        ranking_alias = primary_metric_alias or expected_aliases[-1]
        if time_bucket_expr and not (plan.ranking or plan.order or plan.limit):
            order_by = "\nORDER BY period_start ASC"
        else:
            order_by = self._order_by(plan, analysis_type, ranking_alias)
        # A percentile slice ("en üstteki %10") renders as TOP (N) PERCENT with
        # the ranking ORDER BY, cutting the top/bottom N% of groups. It needs a
        # genuine ordering to be meaningful, so it only applies alongside one.
        if plan.percentile and order_by:
            top = f"TOP ({plan.percentile}) PERCENT "
        else:
            top = (
                f"TOP ({plan.limit}) "
                if plan.limit
                and (
                    analysis_type in {"ranking", "top_n", "bottom_n"}
                    or plan.ranking is not None
                    or plan.order is not None
                )
                else ""
            )
        sql = (
            f"SELECT {top}{', '.join(select_parts)}\n"
            f"{from_clause}"
            f"{where}"
            f"{group_by}"
            f"{having}"
            f"{order_by};"
        )
        result_schema = self._schema_name(analysis_type)
        if analysis_type == "data_quality" and dimensions and result_schema == "CountResult":
            # A scalar metric grouped by any dimension is a series of labelled
            # values, regardless of the metric family (for example branch-level
            # missing-doctor counts).  Returning CountResult here discards that
            # shape and makes result normalisation reject otherwise valid SQL.
            result_schema = "DistributionResult"
        return DeterministicSQL(
            sql=sql,
            result_schema=result_schema,
            expected_aliases=expected_aliases,
            skipped_metrics=skipped,
            metric_aliases=metric_aliases,
        )

    def _list(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        columns = [
            column
            for column in (
                plan.projection
                or [
                    "Id",
                    "BaslangicTarihi",
                    "BitisTarihi",
                    "RandevuDurumu",
                    "GenelRandevuKaynakAdi",
                    "GenelRandevuBolumAdi",
                    "SubeAdi",
                    "RandevuTipiAdi",
                ]
            )
            if self._is_safe_identifier(column)
        ]
        if not columns:
            return UnsupportedPlan("list request has no safe projection")
        top = f"TOP ({plan.limit}) " if plan.limit else ""
        where = self._where(plan)
        order = "DESC" if (plan.order or "DESC") == "DESC" else "ASC"
        order_column = (plan.date_filters[0].column if plan.date_filters else None) or DATE_COLUMN
        sql = (
            f"SELECT {top}{', '.join(columns)}\n"
            f"FROM {VIEW}\n"
            f"{where}"
            f"ORDER BY {order_column} {order};"
        )
        return DeterministicSQL(
            sql=sql,
            result_schema="RawRecordRows",
            expected_aliases=[],
        )

    def _cohort(self, plan: QueryPlan, *, adaptive_retry: bool) -> DeterministicSQL:
        # 'Son dakika' = created within the 24h before the appointment start;
        # negative lead times are excluded (BETWEEN 0 AND 24).
        upper_hour = 48 if adaptive_retry else 24
        cohort_filter = f"DATEDIFF(hour, CreatedDate, BaslangicTarihi) BETWEEN 0 AND {upper_hour}"
        # RandevuDurumu is already expanded below into one count/rate pair for
        # every verified status. Other requested dimensions (branch,
        # department, source...) must remain in the query; otherwise a valid
        # plan such as "geç alınan randevular bölümlerde nasıl sonuç vermiş"
        # silently collapses to one global row.
        dimensions = [
            dimension for dimension in self._dimensions(plan) if dimension != "RandevuDurumu"
        ]
        splits_department = DEPARTMENT_COLUMN in dimensions
        dimension_expr = {
            dimension: (
                f"{_DEPARTMENT_SPLIT_ALIAS}.value"
                if dimension == DEPARTMENT_COLUMN
                else dimension
            )
            for dimension in dimensions
        }
        select_parts = [
            f"{dimension_expr[dimension]} AS {dimension}" for dimension in dimensions
        ]
        select_parts.append("COUNT(*) AS cohort_total_count")
        aliases = [*dimensions, "cohort_total_count"]
        for prefix, value in VERIFIED_STATUS_VALUES.items():
            condition = f"RandevuDurumu = N'{value}'"
            select_parts.append(f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) AS {prefix}_count")
            select_parts.append(
                f"100.0 * SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS {prefix}_rate"
            )
            aliases.extend([f"{prefix}_count", f"{prefix}_rate"])
        # The lead-time window is always applied; any OTHER plan-level
        # scoping (a date range, department, branch, status filter) narrows
        # WHICH appointments are considered for it - e.g. "2025'te son
        # dakika alınan randevular" must restrict to 2025, not silently run
        # the cohort over the entire table. Previously this method took no
        # `plan` at all, so a stated date_filter never made it into the SQL
        # and PlanComplianceValidator's generic per-filter check rejected the
        # (otherwise-correct) cohort SQL outright -> SAFE_ERROR (2026-07-27,
        # live multi-turn testing; the cohort path had never been exercised
        # end-to-end before).
        where = self._where(plan)
        where = f"{where.rstrip()} AND {cohort_filter}" if where else f"WHERE {cohort_filter}"
        from_clause = f"FROM {VIEW}\n"
        if splits_department:
            from_clause += self._department_split_cross_apply()
            where += f" AND {_DEPARTMENT_SPLIT_ALIAS}.value <> ''"
        group_by = (
            "\nGROUP BY " + ", ".join(dimension_expr[dimension] for dimension in dimensions)
            if dimensions
            else ""
        )
        order_by = "\nORDER BY cohort_total_count DESC" if dimensions else ""
        sql = (
            f"SELECT {', '.join(select_parts)}\n"
            f"{from_clause}"
            f"{where}"
            f"{group_by}"
            f"{order_by};"
        )
        return DeterministicSQL(
            sql=sql,
            result_schema="CohortResult",
            expected_aliases=aliases,
        )

    def _period_comparison(
        self, plan: QueryPlan, *, adaptive_retry: bool
    ) -> DeterministicSQL | UnsupportedPlan:
        if len(plan.periods) > 2 and not plan.dimensions:
            return self._multi_period_breakdown(plan)
        current, baseline, current_label, baseline_label = self._period_pair_with_labels(
            plan, adaptive_retry
        )
        # Per-dimension period comparison ("Ocak ile Şubat'ı BÖLÜM BAZINDA
        # kıyasla", "en çok fark olan ilk 5 bölüm"): one row per group with its
        # current-period count, baseline-period count, and the signed
        # difference — ordered by |difference| so the biggest movers lead. Only
        # the plain VOLUME case is grouped; a rate/ratio comparison keeps the
        # scalar two-period shape below (2026-07-29, live UI month-comparison
        # findings).
        if plan.dimensions and not (plan.numerator and plan.denominator) and len(plan.metrics) <= 1:
            grouped = self._period_comparison_grouped(plan, current, baseline)
            if grouped is not None:
                return grouped
        skipped: list[str] = []
        metric_aliases: dict[str, str] = {}
        if plan.numerator and plan.denominator:
            numerator = self._metric_expr(plan.numerator, plan.metric_specs)
            denominator = self._metric_expr(plan.denominator, plan.metric_specs)
            if not numerator or not denominator:
                return UnsupportedPlan(
                    "ratio numerator/denominator mapping is not verified",
                    [m for m in (plan.numerator, plan.denominator) if m],
                )
            cur_num = self._conditional(numerator, current)
            cur_den = self._conditional(denominator, current)
            base_num = self._conditional(numerator, baseline)
            base_den = self._conditional(denominator, baseline)
            select = (
                f"{cur_num} AS current_numerator, {cur_den} AS current_denominator, "
                f"100.0 * {cur_num} / NULLIF({cur_den}, 0) AS current_rate, "
                f"{base_num} AS baseline_numerator, {base_den} AS baseline_denominator, "
                f"100.0 * {base_num} / NULLIF({base_den}, 0) AS baseline_rate, "
                f"(100.0 * {cur_num} / NULLIF({cur_den}, 0)) - (100.0 * {base_num} / NULLIF({base_den}, 0)) AS rate_point_change"
            )
            aliases = [
                "current_numerator",
                "current_denominator",
                "current_rate",
                "baseline_numerator",
                "baseline_denominator",
                "baseline_rate",
                "rate_point_change",
            ]
        else:
            # Multi-metric comparison ("2024 ve 2025 için toplam, gerçekleşen ve
            # gelmeyen randevuyu karşılaştır") renders one current_/baseline_
            # conditional-aggregate pair PER metric. The PRIMARY metric keeps the
            # canonical current_period_count/baseline_period_count aliases so the
            # PeriodComparisonResult contract and its renderer keep working
            # unchanged; the remaining metrics are added as extra columns. Before
            # this the whole plan was rejected and surfaced as "Yanıt
            # Oluşturulamadı" (Codex live UI testing, 2026-07-31).
            requested = plan.metrics or ["appointment_count"]
            resolved, skipped = self._metric_expressions(requested, plan.metric_specs)
            # Simple aggregates can be gated in the outer scan. Composite
            # aggregates (rates/ratios) cannot be wrapped in another CASE
            # without illegal nested aggregates, so they are evaluated in a
            # read-only scalar subquery scoped to the same period and filters.
            conditionable = [
                (metric_id, expression)
                for metric_id, expression in resolved
                if self._can_condition(expression)
            ]
            if not conditionable:
                return UnsupportedPlan(
                    "period comparison metric mapping is not verified", plan.metrics
                )
            filters = self._render_structured_filters(plan)
            scalar_filter_sql = f" AND {' AND '.join(filters)}" if filters else ""

            def period_metric(expression: str, condition: str) -> str:
                if self._can_condition(expression):
                    return self._conditional(expression, condition)
                return f"(SELECT {expression} FROM {VIEW} WHERE ({condition}){scalar_filter_sql})"

            # A plain total makes the most sensible headline number when the
            # question mixed it with status breakdowns; otherwise keep the
            # planner's own ordering.
            primary_index = next(
                (i for i, (mid, _) in enumerate(resolved) if mid == "appointment_count"),
                next(i for i, item in enumerate(resolved) if item in conditionable),
            )
            primary_id, primary = resolved[primary_index]
            current_expr = period_metric(primary, current)
            baseline_expr = period_metric(primary, baseline)
            parts = [
                f"N'{current_label}' AS current_period_label",
                f"N'{baseline_label}' AS baseline_period_label",
                f"{current_expr} AS current_period_count",
                f"{baseline_expr} AS baseline_period_count",
                f"({current_expr}) - ({baseline_expr}) AS absolute_change",
                f"100.0 * (({current_expr}) - ({baseline_expr})) / NULLIF(({baseline_expr}), 0) AS percentage_change",
            ]
            aliases = [
                "current_period_label",
                "baseline_period_label",
                "current_period_count",
                "baseline_period_count",
                "absolute_change",
                "percentage_change",
            ]
            for index, (metric_id, expression) in enumerate(resolved):
                if index == primary_index or not self._is_safe_identifier(metric_id):
                    continue
                cur_metric = period_metric(expression, current)
                base_metric = period_metric(expression, baseline)
                parts.extend(
                    [
                        f"{cur_metric} AS current_{metric_id}",
                        f"{base_metric} AS baseline_{metric_id}",
                        f"({cur_metric}) - ({base_metric}) AS {metric_id}_change",
                    ]
                )
                aliases.extend(
                    [f"current_{metric_id}", f"baseline_{metric_id}", f"{metric_id}_change"]
                )
                metric_aliases[metric_id] = f"current_{metric_id}"
            metric_aliases[primary_id] = "current_period_count"
            select = ", ".join(parts)
        filters = self._render_structured_filters(plan)
        filter_sql = f" AND {' AND '.join(filters)}" if filters else ""
        sql = f"SELECT {select}\nFROM {VIEW}\nWHERE (({current}) OR ({baseline})){filter_sql};"
        return DeterministicSQL(
            sql=sql,
            result_schema="PeriodComparisonResult",
            expected_aliases=aliases,
            skipped_metrics=skipped,
            metric_aliases=metric_aliases,
        )

    def _multi_period_breakdown(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        metric_ids = plan.metrics or ["appointment_count"]
        resolved, skipped = self._metric_expressions(metric_ids, plan.metric_specs)
        if not resolved:
            return UnsupportedPlan("period breakdown metric mapping is not verified", plan.metrics)
        filters = self._render_structured_filters(plan)
        filter_sql = f" AND {' AND '.join(filters)}" if filters else ""
        metric_select = ", ".join(
            f"{expression} AS {self._alias_for_metric(metric_id, 'distribution')}"
            for metric_id, expression in resolved
            if self._is_safe_identifier(metric_id)
        )
        selects = [
            (
                f"SELECT N'{period.label}' AS period_label, {metric_select}\n"
                f"FROM {VIEW}\n"
                f"WHERE {self._period_predicate(period)}{filter_sql}"
            )
            for period in plan.periods
        ]
        sql = "\nUNION ALL\n".join(selects) + "\nORDER BY period_label;"
        aliases = [
            self._alias_for_metric(metric_id, "distribution")
            for metric_id, _ in resolved
            if self._is_safe_identifier(metric_id)
        ]
        return DeterministicSQL(
            sql=sql,
            result_schema="DistributionResult",
            expected_aliases=["period_label", *aliases],
            skipped_metrics=skipped,
            metric_aliases={
                metric_id: self._alias_for_metric(metric_id, "distribution")
                for metric_id, _expression in resolved
                if self._is_safe_identifier(metric_id)
            },
        )

    def _period_comparison_grouped(
        self, plan: QueryPlan, current: str, baseline: str
    ) -> DeterministicSQL | UnsupportedPlan | None:
        """One row per group for a two-period volume comparison. Returns None
        when the sole dimension has no supported grouped shape, so the caller
        falls back to the scalar two-period total."""
        dimension = plan.dimensions[0]
        splits_department = dimension == DEPARTMENT_COLUMN
        if splits_department:
            group_expr = f"{_DEPARTMENT_SPLIT_ALIAS}.value"
            alias = DEPARTMENT_COLUMN
        elif self._is_safe_identifier(dimension):
            group_expr = dimension
            alias = dimension
        else:
            return None
        cur = f"SUM(CASE WHEN ({current}) THEN 1 ELSE 0 END)"
        base = f"SUM(CASE WHEN ({baseline}) THEN 1 ELSE 0 END)"
        select = (
            f"{group_expr} AS {alias}, "
            f"{cur} AS current_period_count, "
            f"{base} AS baseline_period_count, "
            f"({cur}) - ({base}) AS absolute_change"
        )
        aliases = [alias, "current_period_count", "baseline_period_count", "absolute_change"]
        # The period disjunction MUST stay parenthesized: a trailing "AND guard"
        # binds tighter than OR, so an unwrapped "(current) OR (baseline) AND
        # guard" would apply the empty/atomic department guard only to the
        # baseline side and leak empty-department rows from the current side.
        where = f"WHERE (({current}) OR ({baseline}))\n"
        from_clause = f"FROM {VIEW}\n"
        if splits_department:
            from_clause += self._department_split_cross_apply()
            guard = f"{_DEPARTMENT_SPLIT_ALIAS}.value <> ''"
            atomic_guard = self._atomic_department_guard(self._department_filter_values(plan))
            if atomic_guard:
                guard = f"{guard} AND {atomic_guard}"
            if plan.excluded_departments:
                literals = ", ".join(
                    self._unicode_literal(value) for value in plan.excluded_departments
                )
                guard = f"{guard} AND {_DEPARTMENT_SPLIT_ALIAS}.value NOT IN ({literals})"
            where = f"{where.rstrip()} AND {guard}\n"
        top = f"TOP ({plan.limit}) " if plan.limit else ""
        change_direction = self._period_change_direction(plan)
        delta_expr = f"({cur}) - ({base})"
        having = ""
        if change_direction == "increase":
            having = f"\nHAVING {delta_expr} > 0"
            order_by = f"ORDER BY {delta_expr} DESC"
        elif change_direction == "decrease":
            having = f"\nHAVING {delta_expr} < 0"
            order_by = f"ORDER BY {delta_expr} ASC"
        else:
            order_by = f"ORDER BY ABS({delta_expr}) DESC"
        sql = (
            f"SELECT {top}{select}\n"
            f"{from_clause}"
            f"{where}"
            f"GROUP BY {group_expr}\n"
            f"{having}\n"
            f"{order_by};"
        )
        return DeterministicSQL(
            sql=sql,
            # A multi-row breakdown table, not the single-row comparison
            # contract — free-form DistributionResult rows carry the diff column.
            result_schema="DistributionResult",
            expected_aliases=aliases,
        )

    def _period_change_direction(self, plan: QueryPlan) -> str | None:
        for calculation in plan.derived_calculations:
            if calculation == "period_change_direction:increase":
                return "increase"
            if calculation == "period_change_direction:decrease":
                return "decrease"
        return None

    def _entity_comparison(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        """Two-entity comparison ("Kardiyoloji ile Psikiyatri'yi karşılaştır"):
        one conditional-count row per grounded pair value. Only ever built from
        a grounded resolved pair (AI-INTELLIGENCE-016 comparison_pair) — a
        comparison plan without one falls through to the LLM path."""
        grounded = self._grounded_entities(plan)
        if grounded is None:
            return UnsupportedPlan("comparison plan without a grounded two-value entity pair")
        field_name, all_values = grounded
        if len(all_values) > 2:
            # Three or more sides cannot be expressed by this method's
            # pair-shaped contract (current_/baseline_ labels + a single
            # absolute/percentage change) — render a per-entity breakdown.
            return self._entity_breakdown(plan, field_name, all_values)
        values = all_values[:2]
        # The pair contract below hardcodes a conditional COUNT per side. That
        # is only the right answer when the comparison is about VOLUME. When the
        # user asks to compare a RATE/AVERAGE ("Kardiyoloji ile Nöroloji'nin
        # gelmeme ORANINI karşılaştır"), a count comparison is a confidently
        # wrong answer (it reported 18615 vs 6483 appointments instead of the
        # two no-show rates, live 2026-07-28). Delegate any non-count metric to
        # the per-entity breakdown, which computes the requested metric scoped
        # to each side — one clean row per department with its own rate.
        non_count_metrics = [m for m in plan.metrics if m != "appointment_count"]
        if non_count_metrics:
            return self._entity_breakdown(plan, field_name, values)
        current_value, baseline_value = values[0], values[1]
        current_condition = self._entity_condition(field_name, current_value)
        baseline_condition = self._entity_condition(field_name, baseline_value)
        current_expr = f"SUM(CASE WHEN {current_condition} THEN 1 ELSE 0 END)"
        baseline_expr = f"SUM(CASE WHEN {baseline_condition} THEN 1 ELSE 0 END)"
        current_label = current_value.replace("'", "''")
        baseline_label = baseline_value.replace("'", "''")

        # The pair conditions live in the CASE expressions; the WHERE keeps the
        # remaining plan constraints (dates, status, ...) plus an either-entity
        # restriction so COUNT(*) means "rows in this comparison".
        pruned = self._without_pair_filters(plan, field_name)
        where = self._where(pruned)
        either = f"({current_condition} OR {baseline_condition})"
        where = f"{where.rstrip()} AND {either}\n" if where else f"WHERE {either}\n"

        select = (
            f"N'{current_label}' AS current_entity_label, "
            f"N'{baseline_label}' AS baseline_entity_label, "
            f"COUNT(*) AS comparison_total_count, "
            f"{current_expr} AS current_entity_count, "
            f"{baseline_expr} AS baseline_entity_count, "
            f"({current_expr}) - ({baseline_expr}) AS absolute_change, "
            f"100.0 * (({current_expr}) - ({baseline_expr})) / NULLIF(({baseline_expr}), 0) AS percentage_change"
        )
        sql = f"SELECT {select}\nFROM {VIEW}\n{where};"
        aliases = [
            "current_entity_label",
            "baseline_entity_label",
            "comparison_total_count",
            "current_entity_count",
            "baseline_entity_count",
            "absolute_change",
            "percentage_change",
        ]
        return DeterministicSQL(
            sql=sql, result_schema="EntityComparisonResult", expected_aliases=aliases
        )

    def _grounded_entities(self, plan: QueryPlan) -> tuple[str, list[str]] | None:
        """Returns the grounded multi-value entity filter driving a comparison.

        Every grounded value is returned (not just the first two) so a 3+-way
        enumeration can be rendered as a per-entity breakdown; the pair path
        slices what it needs.
        """
        for field_name in ("department", "branch"):
            resolved = plan.resolved_filters.get(field_name)
            if resolved is not None and resolved.grounded and len(resolved.values) >= 2:
                return field_name, list(resolved.values)
        return None

    def _entity_breakdown(
        self, plan: QueryPlan, field_name: str, values: list[str]
    ) -> DeterministicSQL | UnsupportedPlan:
        """Three-or-more entity comparison: one row per requested entity.

        Rendered as a UNION ALL of one aggregate per entity rather than a
        `GROUP BY` over the entity column, because the department column is
        composite (comma-separated, see `_department_containment`) — grouping
        it raw yields combination rows ("Genel Cerrahi, Ameliyathane, ...")
        instead of one clean row per requested entity. A row belonging to two
        of the requested entities is counted under both, which is the correct
        reading of "compare A, B and C".

        Reported as a plain `DistributionResult` so the existing categorical
        analytics/insight/chart/table path handles it with no new contract.
        """
        metric_ids = plan.metrics or ["appointment_count"]
        resolved, skipped = self._metric_expressions(metric_ids, plan.metric_specs)
        if not resolved:
            return UnsupportedPlan("entity breakdown metric mapping is not verified", plan.metrics)
        aliased_metrics = [
            (metric_id, expression, self._alias_for_metric(metric_id, "distribution"))
            for metric_id, expression in resolved
            if self._is_safe_identifier(metric_id)
        ]
        if not aliased_metrics:
            return UnsupportedPlan("entity metric aliases are not safe", metric_ids)
        # The per-entity conditions live in each branch's own WHERE, so the
        # entity filter itself must not also be rendered as a shared clause.
        pruned = self._without_pair_filters(plan, field_name)
        base_where = self._where(pruned)
        branches: list[str] = []
        for value in values:
            condition = self._entity_condition(field_name, value)
            where = (
                f"{base_where.rstrip()} AND {condition}\n" if base_where else f"WHERE {condition}\n"
            )
            branches.append(
                f"SELECT {self._unicode_literal(value)} AS entity_label, "
                + ", ".join(
                    f"{expression} AS {alias}" for _metric_id, expression, alias in aliased_metrics
                )
                + "\n"
                f"FROM {VIEW}\n{where}"
            )
        primary_alias = next(
            (
                alias
                for metric_id, _expression, alias in aliased_metrics
                if metric_id == "appointment_count"
            ),
            aliased_metrics[0][2],
        )
        sql = "UNION ALL\n".join(branches).rstrip() + f"\nORDER BY {primary_alias} DESC;"
        return DeterministicSQL(
            sql=sql,
            result_schema="DistributionResult",
            expected_aliases=["entity_label", *(item[2] for item in aliased_metrics)],
            skipped_metrics=skipped,
            metric_aliases={item[0]: item[2] for item in aliased_metrics},
        )

    def _entity_condition(self, field_name: str, value: str) -> str:
        if field_name == "department":
            cleaned = value.strip().strip(",").strip()
            normalized_column = f"',' + REPLACE({DEPARTMENT_COLUMN}, ', ', ',') + ','"
            return f"{normalized_column} LIKE {self._unicode_literal(f'%,{cleaned},%')}"
        column, _tier = FIELD_COLUMNS.get(field_name, (None, None))
        return f"{column} = {self._unicode_literal(value)}"

    def _without_pair_filters(self, plan: QueryPlan, field_name: str) -> QueryPlan:
        resolved = {key: value for key, value in plan.resolved_filters.items() if key != field_name}
        updates: dict = {"resolved_filters": resolved}
        if field_name == "department":
            updates["department_filter"] = None
        if field_name == "branch":
            updates["branch_filters"] = []
        return plan.model_copy(update=updates)

    def _anomaly(
        self, plan: QueryPlan, *, adaptive_retry: bool
    ) -> DeterministicSQL | UnsupportedPlan:
        dimension = (plan.dimensions or ["SubeAdi"])[0]
        current, baseline = self._period_pair(plan, adaptive_retry)
        # The tracked event comes from the plan's conditional status metric
        # (no_show by default). 'İptal' does not exist in the data, so cancelled
        # anomalies are never built here — the planner marks them unanswerable.
        status_prefix = "no_show"
        for metric_id in plan.metrics:
            root = (
                metric_id[: -len("_count")]
                if metric_id.endswith("_count")
                else (metric_id[: -len("_rate")] if metric_id.endswith("_rate") else None)
            )
            if root and root in VERIFIED_STATUS_VALUES:
                status_prefix = root
                break
        status_value = VERIFIED_STATUS_VALUES[status_prefix]
        event = f"SUM(CASE WHEN RandevuDurumu = N'{status_value}' THEN 1 ELSE 0 END)"
        cur_total = self._conditional("COUNT(*)", current)
        base_total = self._conditional("COUNT(*)", baseline)
        cur_event = self._conditional(event, current)
        base_event = self._conditional(event, baseline)
        sql = (
            f"SELECT {dimension} AS {dimension}, "
            f"{cur_total} AS current_period_count, {base_total} AS baseline_period_count, "
            f"{cur_event} AS current_{status_prefix}_count, {base_event} AS baseline_{status_prefix}_count, "
            f"100.0 * {cur_event} / NULLIF({cur_total}, 0) AS current_{status_prefix}_rate, "
            f"100.0 * {base_event} / NULLIF({base_total}, 0) AS baseline_{status_prefix}_rate, "
            f"(100.0 * {cur_event} / NULLIF({cur_total}, 0)) - (100.0 * {base_event} / NULLIF({base_total}, 0)) AS rate_point_change, "
            f"100.0 * ({cur_event} - {base_event}) / NULLIF({base_event}, 0) AS percentage_change\n"
            f"FROM {VIEW}\n"
            f"WHERE ({current}) OR ({baseline})\n"
            f"GROUP BY {dimension}\n"
            f"ORDER BY rate_point_change {'ASC' if (plan.order or plan.ranking) == 'ASC' else 'DESC'};"
        )
        aliases = [
            dimension,
            "current_period_count",
            "baseline_period_count",
            f"current_{status_prefix}_count",
            f"baseline_{status_prefix}_count",
            f"current_{status_prefix}_rate",
            f"baseline_{status_prefix}_rate",
            "rate_point_change",
            "percentage_change",
        ]
        return DeterministicSQL(sql=sql, result_schema="AnomalyResult", expected_aliases=aliases)

    def _variance(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        dimension = (plan.dimensions or ["DoktorId"])[0]
        if dimension not in self._metric_catalog.dimension_groups.get("organizational", []):
            return UnsupportedPlan(f"unverified variance dimension: {dimension}")
        where = self._where(plan)
        sql = (
            "WITH group_counts AS (\n"
            f"    SELECT {dimension} AS group_key, COUNT(*) AS appointment_count\n"
            f"    FROM {VIEW}\n"
            f"    {where}\n"
            f"    GROUP BY {dimension}\n"
            "), ranked AS (\n"
            "    SELECT group_key, appointment_count, "
            "CUME_DIST() OVER (ORDER BY appointment_count DESC) AS top_rank\n"
            "    FROM group_counts\n"
            ")\n"
            "SELECT COUNT(*) AS group_count, "
            "SUM(appointment_count) AS total_appointments, "
            "AVG(CAST(appointment_count AS FLOAT)) AS average_appointments, "
            "MIN(appointment_count) AS minimum_appointments, "
            "MAX(appointment_count) AS maximum_appointments, "
            "CAST(MAX(appointment_count) AS FLOAT) / NULLIF(AVG(CAST(appointment_count AS FLOAT)), 0) AS max_to_average_ratio, "
            "100.0 * SUM(CASE WHEN top_rank <= 0.10 THEN appointment_count ELSE 0 END) / NULLIF(SUM(appointment_count), 0) AS top_10_percent_share\n"
            "FROM ranked;"
        )
        aliases = [
            "group_count",
            "total_appointments",
            "average_appointments",
            "minimum_appointments",
            "maximum_appointments",
            "max_to_average_ratio",
            "top_10_percent_share",
        ]
        return DeterministicSQL(sql=sql, result_schema="VarianceResult", expected_aliases=aliases)

    def _repeat_behavior(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan | None:
        metric_ids = self._metric_ids(plan, "repeat_behavior")
        if len(metric_ids) != 1:
            return UnsupportedPlan(
                "multi-metric repeat behavior not supported: only one repeat metric can be rendered",
                metric_ids,
            )
        metric_id = metric_ids[0]
        if metric_id == "repeat_patient_count":
            return self._repeat_patient_count(plan)
        if metric_id == "cross_branch_repeat_patient_count":
            return self._cross_branch_repeat_patient_count(plan)
        if metric_id == "same_day_multi_service_patient_count":
            return self._same_day_multi_service_patient_count(plan)
        if metric_id == "same_day_multi_doctor_patient_count":
            return self._same_day_multi_doctor_patient_count(plan)
        if metric_id == "patient_appointment_span_days":
            return self._patient_appointment_span_days(plan)
        if metric_id == "multi_period_patient_overlap_count":
            return self._multi_period_patient_overlap_count(plan)
        return None

    def _repeat_patient_count(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        dimensions = self._dimensions(plan)
        if not all(self._is_safe_identifier(dimension) for dimension in dimensions):
            return UnsupportedPlan("repeat patient count requires safe grouping dimensions")
        conditions = self._where_conditions(plan)
        conditions.append("HastaId IS NOT NULL")
        where = self._where_from_conditions(conditions)
        alias = "repeat_patient_count"
        if dimensions:
            inner_select = ", ".join([*dimensions, "HastaId"])
            group_by = ", ".join([*dimensions, "HastaId"])
            outer_select = ", ".join([*dimensions, f"COUNT(*) AS {alias}"])
            outer_group = ", ".join(dimensions)
            top = f"TOP ({plan.limit}) " if plan.limit else ""
            sql = (
                "WITH patient_repeats AS (\n"
                f"    SELECT {inner_select}, COUNT(*) AS appointment_count\n"
                f"    FROM {VIEW}\n"
                f"    {where}"
                f"    GROUP BY {group_by}\n"
                "    HAVING COUNT(*) > 1\n"
                ")\n"
                f"SELECT {top}{outer_select}\n"
                "FROM patient_repeats\n"
                f"GROUP BY {outer_group}\n"
                f"ORDER BY {alias} {self._ranking_direction(plan)};"
            )
            return DeterministicSQL(
                sql=sql,
                result_schema="DistributionResult",
                expected_aliases=[*dimensions, alias],
                metric_aliases={alias: alias},
            )
        sql = (
            "WITH patient_repeats AS (\n"
            "    SELECT HastaId, COUNT(*) AS appointment_count\n"
            f"    FROM {VIEW}\n"
            f"    {where}"
            "    GROUP BY HastaId\n"
            "    HAVING COUNT(*) > 1\n"
            ")\n"
            f"SELECT COUNT(*) AS {alias}\n"
            "FROM patient_repeats;"
        )
        return DeterministicSQL(
            sql=sql,
            result_schema="CountResult",
            expected_aliases=[alias],
            metric_aliases={alias: alias},
        )

    def _cross_branch_repeat_patient_count(
        self, plan: QueryPlan
    ) -> DeterministicSQL | UnsupportedPlan:
        dimensions = self._dimensions(plan)
        if not all(self._is_safe_identifier(dimension) for dimension in dimensions):
            return UnsupportedPlan("cross-branch repeat count requires safe grouping dimensions")
        base_conditions = self._where_conditions(plan)
        base_conditions.extend(["HastaId IS NOT NULL", "SubeAdi IS NOT NULL"])
        base_where = self._where_from_conditions(base_conditions)
        alias = "cross_branch_repeat_patient_count"
        cte = (
            "WITH cross_branch_patients AS (\n"
            "    SELECT HastaId\n"
            f"    FROM {VIEW}\n"
            f"    {base_where}"
            "    GROUP BY HastaId\n"
            "    HAVING COUNT(*) > 1 AND COUNT(DISTINCT SubeAdi) > 1\n"
            ")\n"
        )
        if dimensions:
            outer_conditions = self._where_conditions(plan, "v")
            outer_conditions.extend(["v.HastaId IS NOT NULL", "v.SubeAdi IS NOT NULL"])
            outer_where = self._where_from_conditions(outer_conditions)
            qualified_dimensions = [f"v.{dimension}" for dimension in dimensions]
            select_dimensions = [f"v.{dimension} AS {dimension}" for dimension in dimensions]
            top = f"TOP ({plan.limit}) " if plan.limit else ""
            sql = cte + (
                f"SELECT {top}{', '.join(select_dimensions)}, "
                f"COUNT(DISTINCT v.HastaId) AS {alias}, COUNT(*) AS appointment_count\n"
                f"FROM {VIEW} v\n"
                "JOIN cross_branch_patients p ON p.HastaId = v.HastaId\n"
                f"{outer_where}"
                f"GROUP BY {', '.join(qualified_dimensions)}\n"
                f"ORDER BY {alias} {self._ranking_direction(plan)};"
            )
            return DeterministicSQL(
                sql=sql,
                result_schema="DistributionResult",
                expected_aliases=[*dimensions, alias, "appointment_count"],
                metric_aliases={alias: alias, "appointment_count": "appointment_count"},
            )
        sql = cte + f"SELECT COUNT(*) AS {alias}\nFROM cross_branch_patients;"
        return DeterministicSQL(
            sql=sql,
            result_schema="CountResult",
            expected_aliases=[alias],
            metric_aliases={alias: alias},
        )

    def _same_day_multi_service_patient_count(
        self, plan: QueryPlan
    ) -> DeterministicSQL | UnsupportedPlan:
        return self._same_day_multi_distinct_patient_count(
            plan,
            distinct_column="HizmetAdi",
            alias="same_day_multi_service_patient_count",
            value_label="services",
        )

    def _same_day_multi_doctor_patient_count(
        self, plan: QueryPlan
    ) -> DeterministicSQL | UnsupportedPlan:
        return self._same_day_multi_distinct_patient_count(
            plan,
            distinct_column="DoktorId",
            alias="same_day_multi_doctor_patient_count",
            value_label="doctors",
        )

    def _same_day_multi_distinct_patient_count(
        self,
        plan: QueryPlan,
        *,
        distinct_column: str,
        alias: str,
        value_label: str,
    ) -> DeterministicSQL | UnsupportedPlan:
        dimensions = self._dimensions(plan)
        if not all(self._is_safe_identifier(dimension) for dimension in dimensions):
            return UnsupportedPlan(
                "same-day multi-distinct count requires safe grouping dimensions"
            )
        if not self._is_safe_identifier(distinct_column):
            return UnsupportedPlan("same-day multi-distinct count requires a safe value column")
        base_conditions = self._where_conditions(plan)
        base_conditions.extend(["HastaId IS NOT NULL", f"{distinct_column} IS NOT NULL"])
        base_where = self._where_from_conditions(base_conditions)
        cte = (
            "WITH qualifying_patient_days AS (\n"
            "    SELECT HastaId, CAST(BaslangicTarihi AS DATE) AS service_day, "
            f"COUNT(*) AS appointment_count, COUNT(DISTINCT {distinct_column}) AS value_count\n"
            f"    FROM {VIEW}\n"
            f"    {base_where}"
            "    GROUP BY HastaId, CAST(BaslangicTarihi AS DATE)\n"
            f"    HAVING COUNT(DISTINCT {distinct_column}) > 1\n"
            ")\n"
        )
        if dimensions:
            if dimensions == [distinct_column]:
                top = f"TOP ({plan.limit}) " if plan.limit else ""
                sql = (
                    f"WITH patient_day_{value_label} AS (\n"
                    "    SELECT HastaId, CAST(BaslangicTarihi AS DATE) AS service_day, "
                    f"{distinct_column}, COUNT(*) AS appointment_count\n"
                    f"    FROM {VIEW}\n"
                    f"    {base_where}"
                    f"    GROUP BY HastaId, CAST(BaslangicTarihi AS DATE), {distinct_column}\n"
                    "),\n"
                    f"qualified_{value_label} AS (\n"
                    f"    SELECT HastaId, service_day, {distinct_column}, appointment_count, "
                    "COUNT(*) OVER (PARTITION BY HastaId, service_day) AS value_count\n"
                    f"    FROM patient_day_{value_label}\n"
                    ")\n"
                    f"SELECT {top}{distinct_column} AS {distinct_column}, COUNT(*) AS {alias}, "
                    "COUNT(DISTINCT HastaId) AS patient_count, SUM(appointment_count) AS appointment_count\n"
                    f"FROM qualified_{value_label}\n"
                    "WHERE value_count > 1\n"
                    f"GROUP BY {distinct_column}\n"
                    f"ORDER BY {alias} {self._ranking_direction(plan)};"
                )
                return DeterministicSQL(
                    sql=sql,
                    result_schema="DistributionResult",
                    expected_aliases=[*dimensions, alias, "patient_count", "appointment_count"],
                    metric_aliases={alias: alias, "appointment_count": "appointment_count"},
                )
            patient_day_columns = list(dict.fromkeys([*dimensions, distinct_column]))
            patient_day_select = ", ".join(patient_day_columns)
            patient_day_group = ", ".join(
                ["HastaId", "CAST(BaslangicTarihi AS DATE)", *patient_day_columns]
            )
            qualified_dimension_select = ", ".join(
                [f"p.{dimension} AS {dimension}" for dimension in dimensions]
            )
            qualified_dimension_group = ", ".join(
                [f"p.{dimension}" for dimension in dimensions] + ["p.HastaId", "p.service_day"]
            )
            select_dimensions = [f"{dimension} AS {dimension}" for dimension in dimensions]
            sql_select_dimensions = ", ".join(select_dimensions)
            sql_group_dimensions = ", ".join(dimensions)
            top = f"TOP ({plan.limit}) " if plan.limit else ""
            sql = (
                f"WITH patient_day_{value_label} AS (\n"
                "    SELECT HastaId, CAST(BaslangicTarihi AS DATE) AS service_day, "
                f"{patient_day_select}, COUNT(*) AS appointment_count\n"
                f"    FROM {VIEW}\n"
                f"    {base_where}"
                f"    GROUP BY {patient_day_group}\n"
                "),\n"
                "qualifying_patient_days AS (\n"
                "    SELECT HastaId, service_day\n"
                f"    FROM patient_day_{value_label}\n"
                "    GROUP BY HastaId, service_day\n"
                f"    HAVING COUNT(DISTINCT {distinct_column}) > 1\n"
                "),\n"
                "qualified_dimension_days AS (\n"
                f"    SELECT {qualified_dimension_select}, p.HastaId, p.service_day, "
                "SUM(p.appointment_count) AS appointment_count\n"
                f"    FROM patient_day_{value_label} p\n"
                "    JOIN qualifying_patient_days q ON q.HastaId = p.HastaId "
                "AND q.service_day = p.service_day\n"
                f"    GROUP BY {qualified_dimension_group}\n"
                ")\n"
                f"SELECT {top}{sql_select_dimensions}, COUNT(*) AS {alias}, "
                "COUNT(DISTINCT HastaId) AS patient_count, SUM(appointment_count) AS appointment_count\n"
                "FROM qualified_dimension_days\n"
                f"GROUP BY {sql_group_dimensions}\n"
                f"ORDER BY {alias} {self._ranking_direction(plan)};"
            )
            return DeterministicSQL(
                sql=sql,
                result_schema="DistributionResult",
                expected_aliases=[*dimensions, alias, "patient_count", "appointment_count"],
                metric_aliases={alias: alias, "appointment_count": "appointment_count"},
            )
        sql = cte + (
            f"SELECT COUNT(*) AS {alias}, COUNT(DISTINCT HastaId) AS patient_count, "
            "SUM(appointment_count) AS appointment_count\n"
            "FROM qualifying_patient_days;"
        )
        return DeterministicSQL(
            sql=sql,
            result_schema="CountResult",
            expected_aliases=[alias, "patient_count", "appointment_count"],
            metric_aliases={alias: alias, "appointment_count": "appointment_count"},
        )

    def _patient_appointment_span_days(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        dimensions = [dimension for dimension in self._dimensions(plan) if dimension != "HastaId"]
        if not all(self._is_safe_identifier(dimension) for dimension in dimensions):
            return UnsupportedPlan("patient appointment span requires safe grouping dimensions")
        conditions = self._where_conditions(plan)
        conditions.extend(["HastaId IS NOT NULL", "BaslangicTarihi IS NOT NULL"])
        where = self._where_from_conditions(conditions)
        alias = "patient_appointment_span_days"
        grouped_columns = [*dimensions, "HastaId"]
        group_by = ", ".join(grouped_columns)
        select_dimensions = f"{', '.join(dimensions)}, " if dimensions else ""
        cte = (
            "WITH patient_spans AS (\n"
            f"    SELECT {select_dimensions}HastaId,\n"
            "           MIN(CAST(BaslangicTarihi AS DATE)) AS first_appointment_date,\n"
            "           MAX(CAST(BaslangicTarihi AS DATE)) AS last_appointment_date,\n"
            "           DATEDIFF(day, MIN(CAST(BaslangicTarihi AS DATE)), MAX(CAST(BaslangicTarihi AS DATE))) AS span_days,\n"
            "           COUNT(*) AS appointment_count\n"
            f"    FROM {VIEW}\n"
            f"    {where}"
            f"    GROUP BY {group_by}\n"
            "    HAVING COUNT(*) > 1\n"
            ")\n"
        )
        patient_limit = self._patient_span_limit(plan)
        if patient_limit:
            sql = cte + (
                f"SELECT TOP ({patient_limit}) HastaId AS HastaId, "
                "first_appointment_date AS first_appointment_date, "
                "last_appointment_date AS last_appointment_date, "
                f"span_days AS {alias}, appointment_count AS appointment_count\n"
                "FROM patient_spans\n"
                f"ORDER BY {alias} DESC;"
            )
            return DeterministicSQL(
                sql=sql,
                result_schema="DistributionResult",
                expected_aliases=[
                    "HastaId",
                    "first_appointment_date",
                    "last_appointment_date",
                    alias,
                    "appointment_count",
                ],
                metric_aliases={alias: alias, "appointment_count": "appointment_count"},
            )
        if dimensions:
            select_parts = [f"{dimension} AS {dimension}" for dimension in dimensions]
            select_parts.extend(
                [
                    f"AVG(CAST(span_days AS FLOAT)) AS {alias}",
                    "MAX(span_days) AS max_patient_appointment_span_days",
                    "MIN(span_days) AS min_patient_appointment_span_days",
                    "COUNT(*) AS patient_count",
                    "SUM(appointment_count) AS appointment_count",
                ]
            )
            sql = cte + (
                f"SELECT {', '.join(select_parts)}\n"
                "FROM patient_spans\n"
                f"GROUP BY {', '.join(dimensions)}\n"
                f"ORDER BY {alias} {self._ranking_direction(plan)};"
            )
            return DeterministicSQL(
                sql=sql,
                result_schema="DistributionResult",
                expected_aliases=[
                    *dimensions,
                    alias,
                    "max_patient_appointment_span_days",
                    "min_patient_appointment_span_days",
                    "patient_count",
                    "appointment_count",
                ],
                metric_aliases={alias: alias, "appointment_count": "appointment_count"},
            )
        sql = cte + (
            f"SELECT AVG(CAST(span_days AS FLOAT)) AS {alias}, "
            "MAX(span_days) AS max_patient_appointment_span_days, "
            "MIN(span_days) AS min_patient_appointment_span_days, "
            "COUNT(*) AS patient_count, "
            "SUM(appointment_count) AS appointment_count\n"
            "FROM patient_spans;"
        )
        return DeterministicSQL(
            sql=sql,
            result_schema="CountResult",
            expected_aliases=[
                alias,
                "max_patient_appointment_span_days",
                "min_patient_appointment_span_days",
                "patient_count",
                "appointment_count",
            ],
            metric_aliases={alias: alias, "appointment_count": "appointment_count"},
        )

    def _multi_period_patient_overlap_count(
        self, plan: QueryPlan
    ) -> DeterministicSQL | UnsupportedPlan:
        period_pair = self._overlap_period_pair(plan)
        if period_pair is None:
            return UnsupportedPlan("patient period overlap requires two explicit periods")
        baseline, current = period_pair
        dimensions = [dimension for dimension in self._dimensions(plan) if dimension != "HastaId"]
        if not all(self._is_safe_identifier(dimension) for dimension in dimensions):
            return UnsupportedPlan("patient period overlap requires safe grouping dimensions")
        non_date_plan = plan.model_copy(update={"date_filters": [], "periods": []})
        base_conditions = [
            f"(({baseline}) OR ({current}))",
            *self._where_conditions(non_date_plan),
            "HastaId IS NOT NULL",
        ]
        base_where = self._where_from_conditions(base_conditions)
        alias = "multi_period_patient_overlap_count"
        cte = (
            "WITH patient_period_presence AS (\n"
            "    SELECT HastaId,\n"
            f"           MAX(CASE WHEN {baseline} THEN 1 ELSE 0 END) AS in_baseline_period,\n"
            f"           MAX(CASE WHEN {current} THEN 1 ELSE 0 END) AS in_current_period\n"
            f"    FROM {VIEW}\n"
            f"    {base_where}"
            "    GROUP BY HastaId\n"
            "),\n"
            "overlap_patients AS (\n"
            "    SELECT HastaId\n"
            "    FROM patient_period_presence\n"
            "    WHERE in_baseline_period = 1 AND in_current_period = 1\n"
            ")\n"
        )
        if dimensions:
            qualified_baseline, qualified_current = self._overlap_period_pair(
                plan, qualifier="v"
            ) or ("", "")
            outer_conditions = [
                f"(({qualified_baseline}) OR ({qualified_current}))",
                *self._where_conditions(non_date_plan, "v"),
                "v.HastaId IS NOT NULL",
            ]
            outer_where = self._where_from_conditions(outer_conditions)
            select_dimensions = [f"v.{dimension} AS {dimension}" for dimension in dimensions]
            group_dimensions = [f"v.{dimension}" for dimension in dimensions]
            top = f"TOP ({plan.limit}) " if plan.limit else ""
            sql = cte + (
                f"SELECT {top}{', '.join(select_dimensions)}, "
                f"COUNT(DISTINCT v.HastaId) AS {alias}, COUNT(*) AS appointment_count\n"
                f"FROM {VIEW} v\n"
                "JOIN overlap_patients p ON p.HastaId = v.HastaId\n"
                f"{outer_where}"
                f"GROUP BY {', '.join(group_dimensions)}\n"
                f"ORDER BY {alias} {self._ranking_direction(plan)};"
            )
            return DeterministicSQL(
                sql=sql,
                result_schema="DistributionResult",
                expected_aliases=[*dimensions, alias, "appointment_count"],
                metric_aliases={alias: alias, "appointment_count": "appointment_count"},
            )
        sql = cte + f"SELECT COUNT(*) AS {alias}\nFROM overlap_patients;"
        return DeterministicSQL(
            sql=sql,
            result_schema="CountResult",
            expected_aliases=[alias],
            metric_aliases={alias: alias},
        )

    def _overlap_period_pair(
        self, plan: QueryPlan, qualifier: str | None = None
    ) -> tuple[str, str] | None:
        if len(plan.periods) >= 2:
            first, second = plan.periods[0], plan.periods[1]
            return (
                self._period_plan_condition(first, qualifier),
                self._period_plan_condition(second, qualifier),
            )
        if len(plan.date_filters) >= 2:
            first, second = plan.date_filters[0], plan.date_filters[1]
            return (
                self._date_filter_condition(first, qualifier),
                self._date_filter_condition(second, qualifier),
            )
        return None

    def _period_plan_condition(self, period, qualifier: str | None = None) -> str:
        prefix = f"{qualifier}." if qualifier else ""
        column = period.column or DATE_COLUMN
        return (
            f"{prefix}{column} >= '{period.start_inclusive}' "
            f"AND {prefix}{column} < '{period.end_exclusive}'"
        )

    def _date_filter_condition(self, date_filter, qualifier: str | None = None) -> str:
        prefix = f"{qualifier}." if qualifier else ""
        column = date_filter.column or DATE_COLUMN
        return (
            f"{prefix}{column} >= '{date_filter.start_date}' "
            f"AND {prefix}{column} < DATEADD(day, 1, '{date_filter.end_date}')"
        )

    def _patient_span_limit(self, plan: QueryPlan) -> int | None:
        folded_question = fold(plan.question)
        patient_rows_requested = (
            plan.limit is not None
            or "listele" in folded_question
            or "en yuksek fark" in folded_question
            or "en uzun fark" in folded_question
        ) and re.search(r"\bhasta\w*\b", folded_question)
        if not patient_rows_requested:
            return None
        if plan.limit:
            return plan.limit
        match = re.search(r"\b(\d{1,3})\s+hasta\w*\b", folded_question)
        if match:
            return int(match.group(1))
        return 10

    def _ranking_direction(self, plan: QueryPlan) -> str:
        return "ASC" if (plan.ranking == "ASC" or plan.order == "ASC") else "DESC"

    def _trend(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        """Builds a chronologically ordered, time-bucketed SELECT for a trend
        plan — never a single scalar total. ``plan.grouping_granularity``
        (day/week/month/year) picks the T-SQL bucket expression; the bucket
        column is always aliased ``period_start`` so AnalyticsEngine's
        temporal-column heuristic recognizes it and classifies the result as
        DataShape.TIME_SERIES.
        """
        metric_ids = self._metric_ids(plan, "time_trend")
        resolved, skipped = self._metric_expressions(metric_ids, plan.metric_specs)
        if not resolved:
            return UnsupportedPlan("no verified metric mapping for trend", metric_ids)

        grain = plan.grouping_granularity or "month"
        date_column = (plan.date_filters[0].column if plan.date_filters else None) or DATE_COLUMN
        bucket_expr = self._time_bucket_expression(grain, date_column)
        aliased_metrics = [
            (metric_id, expression, self._alias_for_metric(metric_id, "time_trend"))
            for metric_id, expression in resolved
            if self._is_safe_identifier(metric_id)
        ]
        if not aliased_metrics:
            return UnsupportedPlan("trend metric aliases are not safe", metric_ids)
        where = self._where(plan)
        sql = (
            f"SELECT {bucket_expr} AS period_start, "
            + ", ".join(
                f"{expression} AS {alias}" for _metric_id, expression, alias in aliased_metrics
            )
            + "\n"
            f"FROM {VIEW}\n"
            f"{where}"
            f"GROUP BY {bucket_expr}\n"
            f"ORDER BY period_start ASC;"
        )
        return DeterministicSQL(
            sql=sql,
            result_schema="TrendResult",
            expected_aliases=["period_start", *(item[2] for item in aliased_metrics)],
            skipped_metrics=skipped,
            metric_aliases={item[0]: item[2] for item in aliased_metrics},
        )

    def _time_bucket_expression(self, grain: str, column: str) -> str:
        if grain == "day":
            return f"CAST({column} AS DATE)"
        if grain == "week":
            return f"DATEADD(WEEK, DATEDIFF(WEEK, 0, {column}), 0)"
        if grain == "year":
            # A yearly bucket reads as the YEAR, not as its first day: rendering
            # DATEFROMPARTS(...) put "2022-01-01" in the Dönem column, which is
            # noise for a year-by-year answer (live UI testing, 2026-07-31).
            # `period_start` carries the "text" presentation format, so a
            # 4-character year is shown verbatim — never thousand-separated —
            # and still sorts correctly, lexicographically and numerically.
            return f"CAST(YEAR({column}) AS NVARCHAR(4))"
        # month (default): SQL Server-standard first-of-month expression.
        return f"DATEFROMPARTS(YEAR({column}), MONTH({column}), 1)"

    def _metric_ids(self, plan: QueryPlan, analysis_type: str) -> list[str]:
        if plan.metrics:
            return plan.metrics
        if analysis_type == "distinct_count":
            return ["unique_patient_count"]
        return ["appointment_count"]

    def _metric_expressions(
        self,
        metric_ids: list[str],
        specs: dict[str, InlineMetric] | None = None,
    ) -> tuple[list[tuple[str, str]], list[str]]:
        expressions, skipped = [], []
        for metric_id in metric_ids:
            expression = self._metric_expr(metric_id, specs)
            if expression:
                expressions.append((metric_id, expression))
            else:
                skipped.append(metric_id)
        return expressions, skipped

    def _metric_expr(
        self, metric_id: str | None, specs: dict[str, InlineMetric] | None = None
    ) -> str | None:
        """Catalog id first, plan-composed spec second.

        The catalog always wins: an inline metric only ever exists for
        something the catalog cannot express, so a name collision means the
        catalog's verified formula is the intended one.
        """
        metric = self._metrics.get(metric_id or "")
        if metric and metric.status != "requires_verified_mapping" and metric.formula:
            return metric.formula
        spec = (specs or {}).get(metric_id or "")
        return self._inline_metric_expr(spec) if spec else None

    def _inline_metric_expr(self, spec: InlineMetric) -> str | None:
        """Renders a plan-composed metric, or None when it cannot be rendered
        safely. Fails closed: the metric is then reported as skipped rather
        than silently dropped from an otherwise-complete answer."""
        if spec.shape != "rate":
            return None
        numerator_predicates = spec.numerator_predicates or (
            [spec.predicate] if spec.predicate is not None else []
        )
        numerator = self._predicate_group_sql(numerator_predicates)
        if numerator is None:
            return None
        if spec.denominator_predicates:
            denominator_conditions = self._predicate_group_sql(spec.denominator_predicates)
            if denominator_conditions is None:
                return None
            denominator = f"SUM(CASE WHEN {denominator_conditions} THEN 1 ELSE 0 END)"
        else:
            denominator = "COUNT(*)"
        return f"100.0 * SUM(CASE WHEN {numerator} THEN 1 ELSE 0 END) / NULLIF({denominator}, 0)"

    def _predicate_group_sql(self, predicates: list[MetricPredicate]) -> str | None:
        """Render an AND-conjunction only when every member is safe.

        A partial conjunction would silently broaden the measured cohort, so
        one invalid member rejects the whole metric instead of being skipped.
        """
        if not predicates:
            return None
        rendered = [self._predicate_sql(predicate) for predicate in predicates]
        if any(predicate is None for predicate in rendered):
            return None
        return " AND ".join(predicate for predicate in rendered if predicate is not None)

    def _predicate_sql(self, predicate: MetricPredicate | None) -> str | None:
        """Renders a grounded predicate. Every part is re-validated here — the
        column against the real column catalog, the operator against
        `_PREDICATE_OPERATORS` — so a malformed predicate can never reach SQL
        even if a caller (or a future LLM plan-filler) constructs one."""
        if predicate is None:
            return None
        if predicate.column not in load_column_catalog().column_names():
            return None
        operator = predicate.operator.upper().strip()
        if operator not in _PREDICATE_OPERATORS:
            return None

        if operator in ("IS NULL", "IS NOT NULL"):
            return f"{predicate.column} {operator}"
        if len(predicate.values) != 1:
            return None
        value = predicate.values[0]
        if predicate.column == DEPARTMENT_COLUMN and operator == "=" and isinstance(value, str):
            # The department column stores comma-separated composites; equality
            # on the raw value never matches a single department, so a share
            # predicate written as `= 'Kardiyoloji'` would read 0% everywhere.
            return self._department_containment([value])
        literal = (
            self._unicode_literal(value)
            if isinstance(value, str)
            else (int(value) if float(value).is_integer() else value)
        )
        return f"{predicate.column} {operator} {literal}"

    def _alias_for_metric(self, metric_id: str, analysis_type: str) -> str:
        if analysis_type in {"ratio", "percentage"} and metric_id.endswith("_rate"):
            return metric_id
        return metric_id

    def _dimensions(self, plan: QueryPlan) -> list[str]:
        return [dimension for dimension in plan.dimensions if self._is_safe_identifier(dimension)]

    def _where(self, plan: QueryPlan) -> str:
        clauses = self._where_conditions(plan)
        return f"WHERE {' AND '.join(clauses)}\n" if clauses else ""

    def _where_conditions(self, plan: QueryPlan, qualifier: str | None = None) -> list[str]:
        clauses: list[str] = []
        seen_dates: set[tuple[str | None, str, str]] = set()
        prefix = f"{qualifier}." if qualifier else ""
        # Several windows on the SAME column are alternatives, not simultaneous
        # requirements: "2022 2023 2024 2025 randevu sayıları" wants the union of
        # those years. ANDing them ("… >= 2022-01-01 AND … < 2022-12-31 AND …
        # >= 2025-01-01 …") is unsatisfiable and silently returns ZERO rows —
        # a wrong answer that passes every compliance check, since each filter
        # really is present (Codex live UI testing, 2026-07-31: "2025 = 0
        # randevu", "Sonuç bulunamadı" on multi-year questions).
        ranges_by_column: dict[str, list[str]] = {}
        for date_filter in plan.date_filters:
            key = (date_filter.column, date_filter.start_date, date_filter.end_date)
            if key in seen_dates:
                continue
            seen_dates.add(key)
            column = date_filter.column or DATE_COLUMN
            ranges_by_column.setdefault(column, []).append(
                f"{prefix}{column} >= '{date_filter.start_date}' AND {prefix}{column} < DATEADD(day, 1, '{date_filter.end_date}')"
            )
        for column_ranges in ranges_by_column.values():
            if len(column_ranges) == 1:
                clauses.append(column_ranges[0])
            else:
                joined = " OR ".join(f"({one})" for one in column_ranges)
                clauses.append(f"({joined})")
        structured = self._render_structured_filters(plan)
        if qualifier:
            structured = [self._qualify_columns(filter_sql, qualifier) for filter_sql in structured]
        clauses.extend(structured)
        return clauses

    def _where_from_conditions(self, clauses: list[str]) -> str:
        return f"WHERE {' AND '.join(clauses)}\n" if clauses else ""

    def _qualify_columns(self, expression: str, qualifier: str) -> str:
        columns = sorted(FILTER_COLUMNS | {DATE_COLUMN, "CreatedDate"}, key=len, reverse=True)
        qualified = expression
        for column in columns:
            qualified = re.sub(
                rf"\b{re.escape(column)}\b",
                f"{qualifier}.{column}",
                qualified,
            )
        return qualified

    def _render_structured_filters(self, plan: QueryPlan) -> list[str]:
        """Render every grounded view filter through one escaped T-SQL path.

        Dedicated branch/department fields, grounded ``resolved_filters``, and
        simple allow-listed ``extra_filters`` all converge here. Values for the
        same column are deduplicated before rendering, preventing the same
        predicate from being applied twice when two compatible plan fields
        carry the same grounded constraint.
        """
        values_by_column: dict[str, list[str]] = {}
        department_values: list[str] = []
        residual_filters: list[str] = []

        def add(column: str, literal: str, raw_text: str | None = None) -> None:
            if column not in FILTER_COLUMNS:
                return
            if column == DEPARTMENT_COLUMN and raw_text is not None:
                # Composite column: collect the raw atomic value; rendered as a
                # containment predicate below, never as =/IN on the raw string.
                cleaned = raw_text.strip().strip(",").strip()
                if cleaned and cleaned not in department_values:
                    department_values.append(cleaned)
                return
            values = values_by_column.setdefault(column, [])
            if literal not in values:
                values.append(literal)

        for value in plan.branch_filters:
            add("SubeAdi", self._unicode_literal(value))
        if plan.department_filter:
            add(
                DEPARTMENT_COLUMN,
                self._unicode_literal(plan.department_filter),
                raw_text=plan.department_filter,
            )

        for field_name, resolved in plan.resolved_filters.items():
            if not resolved.grounded or not resolved.values:
                continue
            column, _tier = FIELD_COLUMNS.get(field_name, (None, None))
            if column is None:
                continue
            for value in resolved.values:
                add(column, self._unicode_literal(value), raw_text=value)

        for extra in plan.extra_filters:
            parsed = self._parse_simple_filter(extra)
            if parsed is not None:
                column, literal = parsed
                add(column, literal, raw_text=self._literal_text(literal))
            elif self._safe_filter(extra):
                # Preserve legacy non-structured constraints (for example the
                # existing negation planner hint). They are not duplicated with
                # canonical structured predicates because parsing failed.
                residual_filters.append(extra)

        rendered = []
        for column, literals in values_by_column.items():
            if len(literals) == 1:
                rendered.append(f"{column} = {literals[0]}")
            else:
                rendered.append(f"{column} IN ({', '.join(literals)})")
        if department_values:
            rendered.append(self._department_containment(department_values))
        return [*rendered, *residual_filters]

    def _department_split_cross_apply(self) -> str:
        """CROSS APPLY that explodes the composite department column into one
        row per atomic value, exposed as `{_DEPARTMENT_SPLIT_ALIAS}.value`.

        `STRING_SPLIT` is unavailable: the live database's compatibility
        level is 110 (SQL Server 2012), well below the 130 `STRING_SPLIT`
        requires, even though the engine itself is newer (verified live,
        2026-07-27). XML `.nodes()` has worked since SQL Server 2005, so it
        is the compatibility-safe alternative. The inner derived table
        materializes `.value(...)` into a plain NVARCHAR column - `.value()`/
        other XML methods are not allowed directly in a GROUP BY, so the
        outer query only ever sees a plain column.

        `&`/`<`/`>` are DROPPED rather than XML-entity-escaped (`&amp;` etc.)
        - standard entities end in `;`, and the LLM-output SQL extractor
        (`OutputParser.parse_sql`, shared with the LLM-generation path) cuts
        the statement off at the FIRST semicolon it finds anywhere in the
        text, silently truncating the query mid-string (2026-07-27, found
        immediately when this method was first live-tested). No real
        department name currently contains any of these characters
        (verified against the live distinct value list), so dropping them
        is a defensive no-op today, not a data-loss risk.
        """
        escaped = (
            f"REPLACE(REPLACE(REPLACE(REPLACE(REPLACE("
            f"{DEPARTMENT_COLUMN}, '&', ''), '<', ''), '>', ''), ', ', ','), "
            f"',', '</i><i>')"
        )
        return (
            f"CROSS APPLY (\n"
            f"    SELECT LTRIM(RTRIM(dept_node.value('.', 'NVARCHAR(4000)'))) AS value\n"
            f"    FROM (SELECT CAST(N'<i>' + {escaped} + N'</i>' AS XML) AS dept_doc) AS dept_wrapped\n"
            f"    CROSS APPLY dept_wrapped.dept_doc.nodes('/i') AS dept_split(dept_node)\n"
            f") AS {_DEPARTMENT_SPLIT_ALIAS}\n"
        )

    def _department_containment(self, values: list[str]) -> str:
        """Delimiter-bounded containment predicate over the composite department
        column: ',Kardiyoloji,' matches the atomic element exactly, so
        'Kardiyoloji' never matches 'Çocuk Kardiyolojisi'."""
        normalized_column = f"',' + REPLACE({DEPARTMENT_COLUMN}, ', ', ',') + ','"
        predicates = [
            f"{normalized_column} LIKE {self._unicode_literal(f'%,{value},%')}" for value in values
        ]
        if len(predicates) == 1:
            return predicates[0]
        return "(" + " OR ".join(predicates) + ")"

    def _department_filter_values(self, plan: QueryPlan) -> list[str]:
        values: list[str] = []
        if plan.department_filter:
            values.append(plan.department_filter)
        resolved = plan.resolved_filters.get("department")
        if resolved is not None and resolved.grounded:
            values.extend(resolved.values)
        return list(dict.fromkeys(value for value in values if value))

    def _atomic_department_guard(self, values: list[str]) -> str:
        if not values:
            return ""
        literals = [self._unicode_literal(value) for value in values]
        if len(literals) == 1:
            return f"{_DEPARTMENT_SPLIT_ALIAS}.value = {literals[0]}"
        return f"{_DEPARTMENT_SPLIT_ALIAS}.value IN ({', '.join(literals)})"

    @staticmethod
    def _literal_text(literal: str) -> str | None:
        """Extracts the raw text from an N'...'/'...' literal; None for numbers."""
        match = re.fullmatch(r"N?'(?P<text>(?:''|[^'])*)'", literal)
        if match is None:
            return None
        return match.group("text").replace("''", "'")

    def _parse_simple_filter(self, expression: str) -> tuple[str, str] | None:
        match = _SIMPLE_FILTER.fullmatch(expression)
        if match is None:
            return None
        column = match.group("column")
        canonical_column = next(
            (candidate for candidate in FILTER_COLUMNS if candidate.lower() == column.lower()),
            None,
        )
        if canonical_column is None:
            return None
        number = match.group("number")
        if number is not None:
            return canonical_column, number
        text_value = (match.group("text") or "").replace("''", "'")
        return canonical_column, self._unicode_literal(text_value)

    def _unicode_literal(self, value: str) -> str:
        return "N'" + value.replace("'", "''") + "'"

    def _having(
        self,
        plan: QueryPlan,
        group_by_columns: list[str],
        metric_exprs: list[tuple[str, str]],
    ) -> str:
        """Renders a HAVING clause for an aggregate threshold, or "".

        Only emitted when the query genuinely groups (a HAVING without GROUP BY
        has no aggregate to bound) and a metric aggregate expression is present.
        The bound is applied to the requested metric's aggregate expression
        directly — SQL Server does not allow the SELECT alias in HAVING — so a
        threshold on "randevu sayısı" becomes `HAVING COUNT(*) < 200`.
        """
        threshold = plan.aggregate_threshold
        if threshold is None or not group_by_columns or not metric_exprs:
            return ""
        if threshold.operator not in {"<", "<=", ">", ">="}:
            return ""
        expression = None
        if threshold.metric is not None:
            expression = next(
                (expr for metric_id, expr in metric_exprs if metric_id == threshold.metric),
                None,
            )
            if expression is None:
                expression = self._metric_expr(threshold.metric, plan.metric_specs)
        if expression is None:
            expression = metric_exprs[0][1]
        value = threshold.value
        rendered = int(value) if float(value).is_integer() else value
        return f"\nHAVING {expression} {threshold.operator} {rendered}"

    def _order_by(self, plan: QueryPlan, analysis_type: str, metric_alias: str) -> str:
        if (
            analysis_type in {"ranking", "top_n", "bottom_n", "distribution", "cross_analysis"}
            or plan.ranking
        ):
            direction = "ASC" if analysis_type == "bottom_n" or plan.ranking == "ASC" else "DESC"
            return f"\nORDER BY {metric_alias} {direction}"
        return ""

    def _schema_name(self, analysis_type: str) -> str:
        mapping = {
            "ratio": "RatioResult",
            "percentage": "RatioResult",
            "conversion": "RatioResult",
            "time_trend": "TrendResult",
            "distribution": "DistributionResult",
            "cross_analysis": "DistributionResult",
            "duration_analysis": "DistributionResult",
            "lead_time_analysis": "DistributionResult",
            "repeat_behavior": "RatioResult",
            "ranking": "DistributionResult",
            "top_n": "DistributionResult",
            "bottom_n": "DistributionResult",
        }
        return mapping.get(analysis_type, "CountResult")

    def _has_share_of_total(self, plan: QueryPlan) -> bool:
        return any(
            calculation.startswith("share_of_total:") for calculation in plan.derived_calculations
        )

    def _period_pair(self, plan: QueryPlan, adaptive_retry: bool) -> tuple[str, str]:
        current, baseline, _, _ = self._period_pair_with_labels(plan, adaptive_retry)
        return current, baseline

    def _period_pair_with_labels(
        self, plan: QueryPlan, adaptive_retry: bool
    ) -> tuple[str, str, str, str]:
        """Uses the two ordered, half-open periods already resolved in QueryPlan."""
        if len(plan.periods) == 2:
            baseline_period, current_period = plan.periods
            baseline = self._period_predicate(baseline_period)
            current = self._period_predicate(current_period)
            return (
                current,
                baseline,
                current_period.label,
                baseline_period.label,
            )
        if len(plan.date_filters) == 2:
            baseline_filter, current_filter = plan.date_filters
            baseline_column = baseline_filter.column or DATE_COLUMN
            current_column = current_filter.column or DATE_COLUMN
            baseline = (
                f"{baseline_column} >= '{baseline_filter.start_date}' "
                f"AND {baseline_column} < DATEADD(day, 1, '{baseline_filter.end_date}')"
            )
            current = (
                f"{current_column} >= '{current_filter.start_date}' "
                f"AND {current_column} < DATEADD(day, 1, '{current_filter.end_date}')"
            )
            return (
                current,
                baseline,
                current_filter.expression or current_filter.start_date,
                baseline_filter.expression or baseline_filter.start_date,
            )
        # A comparison plan carrying exactly ONE resolved window ("2025'te ...
        # düşen bölümler", where the second period was lost in the context
        # merge) must compare THAT window against the one immediately before
        # it. Falling through to the GETDATE()-relative default below silently
        # answered about the last 30 days instead of the year the plan states —
        # a wrong answer, and one PlanComplianceValidator then rejected for the
        # missing date filter (Codex live UI testing, 2026-07-31).
        if len(plan.date_filters) == 1:
            window = plan.date_filters[0]
            span = self._previous_window(window.start_date, window.end_date)
            if span is not None:
                previous_start, previous_end = span
                column = window.column or DATE_COLUMN
                current = (
                    f"{column} >= '{window.start_date}' "
                    f"AND {column} < DATEADD(day, 1, '{window.end_date}')"
                )
                baseline = (
                    f"{column} >= '{previous_start}' "
                    f"AND {column} < DATEADD(day, 1, '{previous_end}')"
                )
                return (
                    current,
                    baseline,
                    window.expression or window.start_date,
                    "önceki dönem",
                )
        if adaptive_retry:
            return LAST_90, PREVIOUS_90, "son 90 gün", "önceki 90 gün"
        return LAST_30, PREVIOUS_30, "son 30 gün", "önceki 30 gün"

    def _previous_window(self, start_date: str, end_date: str) -> tuple[str, str] | None:
        """The equal-length window ending the day before `start_date`."""
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            return None
        if end < start:
            return None
        length = (end - start).days + 1
        previous_end = start - timedelta(days=1)
        return (previous_end - timedelta(days=length - 1)).isoformat(), previous_end.isoformat()

    def _period_predicate(self, period) -> str:
        column = period.column or DATE_COLUMN
        return f"{column} >= '{period.start_inclusive}' AND {column} < '{period.end_exclusive}'"

    def _can_condition(self, expression: str) -> bool:
        """True when `_conditional` can safely gate this metric on a period.

        A composite formula — a rate such as
        `100.0 * SUM(CASE ...) / NULLIF(COUNT(*), 0)` — carries TWO aggregate
        calls inside an arithmetic expression. `_conditional`'s generic fallback
        would wrap the whole thing in another SUM(CASE ...), nesting an
        aggregate inside an aggregate, which SQL Server rejects outright. Such a
        metric can only be compared across periods through the
        numerator/denominator path, never as an extra conditional column.
        """
        normalized = expression.strip()
        if len(_AGGREGATE_CALL.findall(normalized)) != 1:
            return False
        return bool(_LEADING_AGGREGATE.match(normalized)) and normalized.endswith(")")

    def _conditional(self, aggregate: str, condition: str) -> str:
        normalized = aggregate.strip()
        upper = normalized.upper()
        if upper == "COUNT(*)":
            return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"
        distinct_count = re.fullmatch(
            r"COUNT\s*\(\s*DISTINCT\s+(.+?)\s*\)", normalized, re.IGNORECASE
        )
        if distinct_count:
            return f"COUNT(DISTINCT CASE WHEN {condition} THEN {distinct_count.group(1)} END)"
        count = re.fullmatch(r"COUNT\s*\(\s*(.+?)\s*\)", normalized, re.IGNORECASE)
        if count:
            return f"COUNT(CASE WHEN {condition} THEN {count.group(1)} END)"
        simple_aggregate = re.fullmatch(
            r"(SUM|AVG|MIN|MAX)\s*\(\s*(.+?)\s*\)", normalized, re.IGNORECASE
        )
        if simple_aggregate and not upper.startswith("SUM(CASE"):
            function, value = simple_aggregate.groups()
            else_value = " ELSE 0" if function.upper() == "SUM" else ""
            return f"{function.upper()}(CASE WHEN {condition} THEN {value}{else_value} END)"
        if upper.startswith("SUM(CASE"):
            inner = normalized[len("SUM(") : -1]
            return f"SUM(CASE WHEN {condition} THEN ({inner}) ELSE 0 END)"
        return f"SUM(CASE WHEN {condition} THEN {normalized} ELSE 0 END)"

    def _safe_filter(self, expression: str) -> bool:
        lowered = expression.lower()
        unsafe = (";", "--", "/*", "*/", "drop ", "delete ", "update ", "insert ")
        return not any(marker in lowered for marker in unsafe)

    def _is_safe_identifier(self, identifier: str) -> bool:
        return identifier.replace("_", "").replace(".", "").isalnum()
