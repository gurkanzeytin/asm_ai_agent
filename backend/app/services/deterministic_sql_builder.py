"""Deterministic SQL generation from QueryPlan.

This builder covers catalog-backed analytical plans for the SQL Server
appointment reporting view. It intentionally returns unsupported for plans that
need schema invention or unverified metric mappings; SQLService can then use
the existing LLM fallback path.
"""

# ruff: noqa: E501

import re
from dataclasses import dataclass, field

from app.database_intelligence.value_catalog import FIELD_COLUMNS
from app.planning.models import QueryPlan
from app.semantics.catalog import load_metric_catalog

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
    "list",
    "adaptive_time_comparison",
    "percentage_change",
    "comparison",
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
        analysis_type = self._analysis_type(plan)
        if analysis_type not in SUPPORTED_ANALYSIS_TYPES:
            return UnsupportedPlan(f"unsupported analysis type: {analysis_type}")
        if analysis_type == "cohort_analysis":
            return self._cohort(adaptive_retry=adaptive_retry)
        if analysis_type in {
            "period_comparison",
            "baseline_comparison",
            "adaptive_time_comparison",
            "percentage_change",
        }:
            return self._period_comparison(plan, adaptive_retry=adaptive_retry)
        if analysis_type == "comparison":
            return self._entity_comparison(plan)
        if analysis_type == "anomaly_comparison":
            return self._anomaly(plan, adaptive_retry=adaptive_retry)
        if analysis_type == "variance_analysis":
            return self._variance(plan)
        if analysis_type == "time_trend":
            return self._trend(plan)
        if analysis_type == "list":
            return self._list(plan)
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
        metric_exprs, skipped = self._metric_expressions(metric_ids)
        if not metric_exprs:
            return UnsupportedPlan("no verified metric mapping", skipped)

        dimensions = self._dimensions(plan)
        select_parts = [f"{dimension} AS {dimension}" for dimension in dimensions]
        expected_aliases = list(dimensions)
        metric_aliases: dict[str, str] = {}
        for metric_id, expression in metric_exprs:
            alias = self._alias_for_metric(metric_id, analysis_type)
            select_parts.append(f"{expression} AS {alias}")
            expected_aliases.append(alias)
            metric_aliases[metric_id] = alias
        where = self._where(plan)
        group_by = f"\nGROUP BY {', '.join(dimensions)}" if dimensions else ""
        order_by = self._order_by(plan, analysis_type, expected_aliases[-1])
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
            f"FROM {VIEW}\n"
            f"{where}"
            f"{group_by}"
            f"{order_by};"
        )
        return DeterministicSQL(
            sql=sql,
            result_schema=self._schema_name(analysis_type),
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

    def _cohort(self, *, adaptive_retry: bool) -> DeterministicSQL:
        # 'Son dakika' = created within the 24h before the appointment start;
        # negative lead times are excluded (BETWEEN 0 AND 24).
        upper_hour = 48 if adaptive_retry else 24
        cohort_filter = f"DATEDIFF(hour, CreatedDate, BaslangicTarihi) BETWEEN 0 AND {upper_hour}"
        select_parts = ["COUNT(*) AS cohort_total_count"]
        aliases = ["cohort_total_count"]
        for prefix, value in VERIFIED_STATUS_VALUES.items():
            condition = f"RandevuDurumu = N'{value}'"
            select_parts.append(f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) AS {prefix}_count")
            select_parts.append(
                f"100.0 * SUM(CASE WHEN {condition} THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS {prefix}_rate"
            )
            aliases.extend([f"{prefix}_count", f"{prefix}_rate"])
        sql = f"SELECT {', '.join(select_parts)}\n" f"FROM {VIEW}\n" f"WHERE {cohort_filter};"
        return DeterministicSQL(sql=sql, result_schema="CohortResult", expected_aliases=aliases)

    def _period_comparison(
        self, plan: QueryPlan, *, adaptive_retry: bool
    ) -> DeterministicSQL | UnsupportedPlan:
        current, baseline, current_label, baseline_label = self._period_pair_with_labels(
            plan, adaptive_retry
        )
        if plan.numerator and plan.denominator:
            numerator = self._metric_expr(plan.numerator)
            denominator = self._metric_expr(plan.denominator)
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
            if len(plan.metrics) > 1:
                return UnsupportedPlan(
                    "multi-metric period comparison not supported: only a single "
                    "metric can be compared across periods today",
                    plan.metrics,
                )
            metric = self._metric_expr((plan.metrics or ["appointment_count"])[0])
            if not metric:
                return UnsupportedPlan(
                    "period comparison metric mapping is not verified", plan.metrics
                )
            current_expr = self._conditional(metric, current)
            baseline_expr = self._conditional(metric, baseline)
            select = (
                f"N'{current_label}' AS current_period_label, "
                f"N'{baseline_label}' AS baseline_period_label, "
                f"{current_expr} AS current_period_count, "
                f"{baseline_expr} AS baseline_period_count, "
                f"({current_expr}) - ({baseline_expr}) AS absolute_change, "
                f"100.0 * (({current_expr}) - ({baseline_expr})) / NULLIF(({baseline_expr}), 0) AS percentage_change"
            )
            aliases = [
                "current_period_label",
                "baseline_period_label",
                "current_period_count",
                "baseline_period_count",
                "absolute_change",
                "percentage_change",
            ]
        sql = f"SELECT {select}\nFROM {VIEW}\nWHERE ({current}) OR ({baseline});"
        return DeterministicSQL(
            sql=sql, result_schema="PeriodComparisonResult", expected_aliases=aliases
        )

    def _entity_comparison(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        """Two-entity comparison ("Kardiyoloji ile Psikiyatri'yi karşılaştır"):
        one conditional-count row per grounded pair value. Only ever built from
        a grounded resolved pair (AI-INTELLIGENCE-016 comparison_pair) — a
        comparison plan without one falls through to the LLM path."""
        pair = self._grounded_pair(plan)
        if pair is None:
            return UnsupportedPlan(
                "comparison plan without a grounded two-value entity pair"
            )
        field_name, values = pair
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
        where = (
            f"{where.rstrip()} AND {either}\n" if where else f"WHERE {either}\n"
        )

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

    def _grounded_pair(self, plan: QueryPlan) -> tuple[str, list[str]] | None:
        for field_name in ("department", "branch"):
            resolved = plan.resolved_filters.get(field_name)
            if resolved is not None and resolved.grounded and len(resolved.values) >= 2:
                return field_name, list(resolved.values[:2])
        return None

    def _entity_condition(self, field_name: str, value: str) -> str:
        if field_name == "department":
            cleaned = value.strip().strip(",").strip()
            normalized_column = f"',' + REPLACE({DEPARTMENT_COLUMN}, ', ', ',') + ','"
            return f"{normalized_column} LIKE {self._unicode_literal(f'%,{cleaned},%')}"
        column, _tier = FIELD_COLUMNS.get(field_name, (None, None))
        return f"{column} = {self._unicode_literal(value)}"

    def _without_pair_filters(self, plan: QueryPlan, field_name: str) -> QueryPlan:
        resolved = {
            key: value for key, value in plan.resolved_filters.items() if key != field_name
        }
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

    def _trend(self, plan: QueryPlan) -> DeterministicSQL | UnsupportedPlan:
        """Builds a chronologically ordered, time-bucketed SELECT for a trend
        plan — never a single scalar total. ``plan.grouping_granularity``
        (day/week/month/year) picks the T-SQL bucket expression; the bucket
        column is always aliased ``period_start`` so AnalyticsEngine's
        temporal-column heuristic recognizes it and classifies the result as
        DataShape.TIME_SERIES.
        """
        metric_ids = self._metric_ids(plan, "time_trend")
        if len(metric_ids) > 1:
            return UnsupportedPlan(
                "multi-metric trend not supported: only a single metric can be "
                "time-bucketed today",
                metric_ids,
            )
        metric_id = metric_ids[0]
        metric_expr = self._metric_expr(metric_id)
        if not metric_expr:
            return UnsupportedPlan("no verified metric mapping for trend", metric_ids)

        grain = plan.grouping_granularity or "month"
        date_column = (plan.date_filters[0].column if plan.date_filters else None) or DATE_COLUMN
        bucket_expr = self._time_bucket_expression(grain, date_column)
        alias = self._alias_for_metric(metric_id, "time_trend")
        where = self._where(plan)
        sql = (
            f"SELECT {bucket_expr} AS period_start, {metric_expr} AS {alias}\n"
            f"FROM {VIEW}\n"
            f"{where}"
            f"GROUP BY {bucket_expr}\n"
            f"ORDER BY period_start ASC;"
        )
        return DeterministicSQL(
            sql=sql, result_schema="TrendResult", expected_aliases=["period_start", alias]
        )

    def _time_bucket_expression(self, grain: str, column: str) -> str:
        if grain == "day":
            return f"CAST({column} AS DATE)"
        if grain == "week":
            return f"DATEADD(WEEK, DATEDIFF(WEEK, 0, {column}), 0)"
        if grain == "year":
            return f"DATEFROMPARTS(YEAR({column}), 1, 1)"
        # month (default): SQL Server-standard first-of-month expression.
        return f"DATEFROMPARTS(YEAR({column}), MONTH({column}), 1)"

    def _metric_ids(self, plan: QueryPlan, analysis_type: str) -> list[str]:
        if plan.metrics:
            return plan.metrics
        if analysis_type == "distinct_count":
            return ["unique_patient_count"]
        return ["appointment_count"]

    def _metric_expressions(self, metric_ids: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
        expressions, skipped = [], []
        for metric_id in metric_ids:
            expression = self._metric_expr(metric_id)
            if expression:
                expressions.append((metric_id, expression))
            else:
                skipped.append(metric_id)
        return expressions, skipped

    def _metric_expr(self, metric_id: str | None) -> str | None:
        metric = self._metrics.get(metric_id or "")
        if not metric or metric.status == "requires_verified_mapping" or not metric.formula:
            return None
        return metric.formula

    def _alias_for_metric(self, metric_id: str, analysis_type: str) -> str:
        if analysis_type in {"ratio", "percentage"} and metric_id.endswith("_rate"):
            return metric_id
        return metric_id

    def _dimensions(self, plan: QueryPlan) -> list[str]:
        return [
            dimension for dimension in plan.dimensions[:2] if self._is_safe_identifier(dimension)
        ]

    def _where(self, plan: QueryPlan) -> str:
        clauses: list[str] = []
        for date_filter in plan.date_filters:
            column = date_filter.column or DATE_COLUMN
            clauses.append(
                f"{column} >= '{date_filter.start_date}' AND {column} < DATEADD(day, 1, '{date_filter.end_date}')"
            )
        clauses.extend(self._render_structured_filters(plan))
        return f"WHERE {' AND '.join(clauses)}\n" if clauses else ""

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

    def _department_containment(self, values: list[str]) -> str:
        """Delimiter-bounded containment predicate over the composite department
        column: ',Kardiyoloji,' matches the atomic element exactly, so
        'Kardiyoloji' never matches 'Çocuk Kardiyolojisi'."""
        normalized_column = f"',' + REPLACE({DEPARTMENT_COLUMN}, ', ', ',') + ','"
        predicates = [
            f"{normalized_column} LIKE {self._unicode_literal(f'%,{value},%')}"
            for value in values
        ]
        if len(predicates) == 1:
            return predicates[0]
        return "(" + " OR ".join(predicates) + ")"

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
            "ranking": "DistributionResult",
            "top_n": "DistributionResult",
            "bottom_n": "DistributionResult",
        }
        return mapping.get(analysis_type, "CountResult")

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
        if adaptive_retry:
            return LAST_90, PREVIOUS_90, "son 90 gün", "önceki 90 gün"
        return LAST_30, PREVIOUS_30, "son 30 gün", "önceki 30 gün"

    def _period_predicate(self, period) -> str:
        column = period.column or DATE_COLUMN
        return f"{column} >= '{period.start_inclusive}' " f"AND {column} < '{period.end_exclusive}'"

    def _conditional(self, aggregate: str, condition: str) -> str:
        normalized = aggregate.strip()
        upper = normalized.upper()
        if upper == "COUNT(*)":
            return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"
        distinct_count = re.fullmatch(
            r"COUNT\s*\(\s*DISTINCT\s+(.+?)\s*\)", normalized, re.IGNORECASE
        )
        if distinct_count:
            return f"COUNT(DISTINCT CASE WHEN {condition} " f"THEN {distinct_count.group(1)} END)"
        count = re.fullmatch(r"COUNT\s*\(\s*(.+?)\s*\)", normalized, re.IGNORECASE)
        if count:
            return f"COUNT(CASE WHEN {condition} THEN {count.group(1)} END)"
        simple_aggregate = re.fullmatch(
            r"(SUM|AVG|MIN|MAX)\s*\(\s*(.+?)\s*\)", normalized, re.IGNORECASE
        )
        if simple_aggregate and not upper.startswith("SUM(CASE"):
            function, value = simple_aggregate.groups()
            else_value = " ELSE 0" if function.upper() == "SUM" else ""
            return f"{function.upper()}(CASE WHEN {condition} THEN {value}" f"{else_value} END)"
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
