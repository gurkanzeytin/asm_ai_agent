import logging
import re
from datetime import date as _date
from datetime import timedelta

import sqlglot
from sqlglot import exp

from app.planning.models import ComplianceResult, QueryPlan

logger = logging.getLogger(__name__)

_FOLD_TABLE = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ğ": "g",
        "Ğ": "g",
        "ş": "s",
        "Ş": "s",
        "ç": "c",
        "Ç": "c",
        "ö": "o",
        "Ö": "o",
        "ü": "u",
        "Ü": "u",
    }
)

_AGGREGATES = {"COUNT": "count(", "SUM": "sum(", "AVG": "avg("}

# AI-INTELLIGENCE-016: fields resolved via app.planning.value_resolver whose
# grounding is checked generically here. branch/department keep their own
# dedicated checks above/below for backward compatibility; appointment_status
# is excluded because it already has an independent, pre-existing grounded
# mechanism (curated app/resources/view_semantics.json status_filters ->
# plan.extra_filters), unrelated to this resolver.
_GROUNDABLE_FIELD_COLUMNS: dict[str, str] = {
    "service": "HizmetAdi",
    "category": "KategoriAdi",
    "appointment_source": "GenelRandevuKaynakAdi",
    "appointment_type": "RandevuTipiAdi",
    "nationality": "Uyruk",
    "gender": "CinsiyetId",
}
_PLANNED_FILTER_COLUMNS = {
    "RandevuDurumu",
    "CinsiyetId",
    "Uyruk",
    "RandevuTipiAdi",
    "HizmetAdi",
    "KategoriAdi",
    "GenelRandevuKaynakAdi",
    "GenelRandevuBolumAdi",
    "SubeAdi",
    "DoktorId",
}
_SIMPLE_PLANNED_FILTER = re.compile(
    r"^\s*\[?(?P<column>[A-Za-z_][A-Za-z0-9_]*)\]?\s*=\s*"
    r"(?:(?:N)?'(?P<text>(?:''|[^'])*)'|(?P<number>-?\d+(?:\.\d+)?))\s*$",
    re.IGNORECASE,
)


class PlanComplianceValidator:
    """Verifies that generated SQL implements every QueryPlan constraint (AG-022).

    Purely lexical and deterministic — checks that each planned constraint is
    visibly present in the SQL. A missing constraint triggers the existing
    single repair attempt; it never adds an LLM call of its own.
    """

    def check(
        self,
        sql: str,
        plan: QueryPlan,
        expected_aliases: list[str] | None = None,
        deterministic: bool = False,
    ) -> ComplianceResult:
        folded_sql = sql.translate(_FOLD_TABLE).lower()
        missing: list[str] = []

        for date_filter in plan.date_filters:
            # Both bounds must be present - `and` here would only flag a
            # filter as missing when NEITHER bound appears, letting a SQL that
            # kept the lower bound but silently dropped the upper one (e.g.
            # "haziran ayında" rendered as "BaslangicTarihi >= '2026-06-01'"
            # with no upper bound, matching every appointment from June 1st
            # onward forever) pass compliance undetected (2026-07-24).
            # The upper bound may legitimately appear either as the inclusive
            # end_date itself (deterministic builder: "< DATEADD(day, 1,
            # 'end_date')") or as its half-open exclusive form, end_date + 1
            # day (period-comparison SQL: "< 'end_date_plus_one'") - both
            # render the exact same date range, only the literal differs.
            end_present = date_filter.end_date in folded_sql or (
                self._exclusive_end(date_filter.end_date) in folded_sql
            )
            if date_filter.start_date not in folded_sql or not end_present:
                missing.append(
                    f"date filter {date_filter.start_date}..{date_filter.end_date} "
                    f"('{date_filter.expression}')"
                )

        if plan.department_filter:
            if not any(
                self._contains_filter_predicate(sql, column, plan.department_filter)
                or self._contains_containment_predicate(sql, column, plan.department_filter)
                for column in ("GenelRandevuBolumAdi", "bolum_adi")
            ):
                missing.append(f"department filter '{plan.department_filter}'")

        # AI-INTELLIGENCE-015: a branch (SubeAdi) VALUE filter may only ever
        # come from a grounded plan.branch_filters entry — never from a
        # generic organizational phrase ("tüm aile sağlığı merkezleri") or the
        # LLM's own free-text guess. Grouping by SubeAdi (GROUP BY) is
        # unaffected; only an actual predicate (=, LIKE, IN) is checked.
        if not plan.branch_filters and re.search(
            r"subeadi\s*(?:=|like|in\s*\()", folded_sql
        ):
            missing.append(
                "ungrounded SubeAdi value filter (plan.branch_filters is empty — "
                "a generic scope phrase or free-text guess must never become a "
                "branch value predicate)"
            )
        if plan.branch_filters:
            if not all(
                self._contains_filter_predicate(sql, "SubeAdi", value)
                for value in plan.branch_filters
            ):
                missing.append(f"branch filter {sorted(plan.branch_filters)}")

        # Curated status predicates and other allow-listed simple extra
        # filters are planned constraints too. They must be rendered as real
        # predicates, using Unicode T-SQL literals when the value is non-ASCII;
        # merely mentioning the value elsewhere in SQL is not compliant.
        for extra_filter in plan.extra_filters:
            parsed = self._parse_planned_filter(extra_filter)
            if parsed is None:
                continue
            column, value = parsed
            if not self._contains_filter_predicate(sql, column, value):
                missing.append(f"planned filter {column} = {value!r}")

        # An explicit single-day date ("bugün"/"dün"/"yarın") must never be
        # rendered as a relative DATEADD lookback offset (e.g. the LLM
        # inventing 'DATEADD(day, -90, ...)' for 'bugünkü') — the resolved
        # date is already a literal boundary in the plan.
        for date_filter in plan.date_filters:
            if date_filter.start_date == date_filter.end_date and re.search(
                r"dateadd\s*\(\s*day\s*,\s*-\d+", folded_sql
            ):
                missing.append(
                    f"explicit single-day date '{date_filter.expression}' must not be "
                    "rendered as a relative DATEADD lookback offset"
                )

        # AI-INTELLIGENCE-016: a value filter on any of these columns may only
        # come from a grounded plan.resolved_filters entry — same discipline
        # as the SubeAdi guard above, generalized to the other resolver fields.
        for gfield, gcolumn in _GROUNDABLE_FIELD_COLUMNS.items():
            folded_column = gcolumn.translate(_FOLD_TABLE).lower()
            has_predicate = bool(
                re.search(rf"{folded_column}\s*(?:=|like|in\s*\()", folded_sql)
            )
            resolved = plan.resolved_filters.get(gfield)
            is_grounded = bool(resolved and resolved.grounded and resolved.values)
            if has_predicate and not is_grounded:
                missing.append(
                    f"ungrounded {gcolumn} value filter (no grounded "
                    f"resolved_filters['{gfield}'] entry)"
                )
            if is_grounded:
                if not all(
                    self._contains_filter_predicate(sql, gcolumn, value)
                    for value in resolved.values
                ):
                    missing.append(f"{gfield} filter {sorted(resolved.values)}")

        if plan.aggregation:
            aggregation = plan.aggregation.upper()
            head = re.match(r"[A-Z]+", aggregation)
            function_name = head.group(0) if head else ""
            if function_name == "COUNT":
                has_conditional_sum = bool(
                    plan.periods and "sum(" in folded_sql and "case" in folded_sql
                )
                if "count(" not in folded_sql and not has_conditional_sum:
                    missing.append(f"aggregation {plan.aggregation}")
                elif "DISTINCT" in aggregation and "distinct" not in folded_sql:
                    missing.append(f"aggregation {plan.aggregation} (DISTINCT required)")
            elif function_name in ("SUM", "AVG", "MIN", "MAX"):
                if f"{function_name.lower()}(" not in folded_sql:
                    missing.append(f"aggregation {plan.aggregation}")
            else:
                marker = _AGGREGATES.get(plan.aggregation, "")
                if marker and marker not in folded_sql:
                    missing.append(f"aggregation {plan.aggregation}")

        # Catalog-driven analytics: ratio plans need a division; grouping dimensions
        # must be visibly present in the SQL.
        if plan.numerator and plan.denominator and "/" not in folded_sql:
            missing.append(f"ratio division {plan.numerator}/{plan.denominator}")
        if (plan.numerator and plan.denominator) or plan.analysis_type in ("ratio", "percentage"):
            if "nullif" not in folded_sql:
                missing.append("ratio division-by-zero protection (NULLIF)")
        for dimension in plan.dimensions:
            if not re.search(rf"\b{re.escape(dimension.lower())}\b", folded_sql):
                missing.append(f"dimension column {dimension}")
            if self._requires_grouping(plan) and not self._group_by_contains(folded_sql, dimension):
                missing.append(f"dimension GROUP BY {dimension}")

        for alias in expected_aliases or []:
            if not re.search(rf"\bas\s+{re.escape(alias.lower())}\b", folded_sql):
                missing.append(f"expected result alias {alias}")

        if self._requires_aggregate_shape(plan) and self._looks_like_raw_detail_projection(
            folded_sql
        ):
            missing.append("raw detail projection in aggregate analysis")

        if plan.analysis_type == "cohort_analysis":
            if (
                "datediff(hour" not in folded_sql
                or "createddate" not in folded_sql
                or "baslangictarihi" not in folded_sql
            ):
                missing.append("cohort lead-time filter")
            if not re.search(r"between\s+0\s+and\s+(24|48)", folded_sql):
                missing.append("cohort non-negative 24/48 hour window")

        if plan.analysis_type == "time_trend" and plan.grouping_granularity:
            if "group by" not in folded_sql:
                missing.append("trend time-bucket GROUP BY")
            if "order by" not in folded_sql:
                missing.append("trend chronological ORDER BY")
            if self._looks_like_raw_detail_projection(folded_sql):
                missing.append("raw detail projection in trend analysis")

        if (
            plan.analysis_type
            in (
                "period_comparison",
                "baseline_comparison",
                "adaptive_time_comparison",
                "percentage_change",
                "anomaly_comparison",
            )
            or plan.baseline_period
        ):
            if "current_" not in folded_sql:
                missing.append("current period metrics")
            if "baseline_" not in folded_sql:
                missing.append("baseline period metrics")
            if plan.periods:
                missing.extend(self._period_aggregate_issues(sql, plan))
            elif "dateadd(day, -30" in folded_sql and "dateadd(day, -60" not in folded_sql:
                missing.append("period comparison baseline window")
            if "where" in folded_sql and " or " not in folded_sql:
                missing.append("period comparison WHERE must include both periods")

        if plan.analysis_type == "anomaly_comparison" and re.search(r"\bhaving\b", folded_sql):
            missing.append("minimum sample size must not be applied as HAVING")

        if plan.ranking and "order by" not in folded_sql:
            missing.append(f"ranking (ORDER BY ... {plan.ranking})")

        # SQL Server bounds results with TOP (n) / OFFSET-FETCH; LIMIT is legacy syntax.
        if plan.limit and not re.search(
            rf"\btop\s*\(?\s*{plan.limit}\s*\)?|\bfetch\s+next\s+{plan.limit}\s+rows"
            rf"|\blimit\s+{plan.limit}\b",
            folded_sql,
        ):
            missing.append(f"row bound TOP ({plan.limit})")

        if plan.projection:
            select_clause = self._select_clause(folded_sql)
            if select_clause and plan.projection[0].lower() not in select_clause:
                missing.append(f"projection column {plan.projection[0]}")

        for step in plan.join_path:
            for table in (step.from_table, step.to_table):
                if not re.search(rf"\b{re.escape(table.lower())}\b", folded_sql):
                    missing.append(f"join table {table}")

        # Multi-metric coverage: when the plan requests more than one metric,
        # every one of them must be visibly present as its own result alias —
        # independent of the `expected_aliases` check above (only populated for
        # the deterministic path), so this also catches an LLM-generated SQL
        # that silently dropped one of several requested metrics. Single-metric
        # plans are intentionally excluded: many analysis shapes (period
        # comparison, anomaly, trend, cohort, variance) alias their one metric
        # with a fixed, non-metric_id name (e.g. "current_period_count") by
        # long-established, already-tested design — only genuine multi-metric
        # coverage is new ground here.
        missing_metrics = (
            sorted(
                {
                    metric_id
                    for metric_id in plan.metrics
                    if not re.search(rf"\bas\s+{re.escape(metric_id.lower())}\b", folded_sql)
                }
            )
            if len(plan.metrics) > 1
            else []
        )
        missing_dimensions = sorted(
            {
                dimension
                for dimension in plan.dimensions
                if not re.search(rf"\b{re.escape(dimension.lower())}\b", folded_sql)
            }
        )

        result = ComplianceResult(
            compliant=not missing and not missing_metrics and not missing_dimensions,
            missing=sorted(set(missing)),
            missing_metrics=missing_metrics,
            missing_dimensions=missing_dimensions,
        )
        logger.info(
            "Plan compliance check: compliant=%s missing=%s missing_metrics=%s "
            "missing_dimensions=%s",
            result.compliant,
            result.missing or "none",
            result.missing_metrics or "none",
            result.missing_dimensions or "none",
            extra={
                "compliant": result.compliant,
                "missing_constraints": result.missing,
                "missing_metrics": result.missing_metrics,
                "missing_dimensions": result.missing_dimensions,
            },
        )
        return result

    def _parse_planned_filter(self, expression: str) -> tuple[str, str] | None:
        match = _SIMPLE_PLANNED_FILTER.fullmatch(expression)
        if match is None:
            return None
        column = next(
            (
                candidate
                for candidate in _PLANNED_FILTER_COLUMNS
                if candidate.lower() == match.group("column").lower()
            ),
            None,
        )
        if column is None:
            return None
        value = match.group("number")
        if value is None:
            value = (match.group("text") or "").replace("''", "'")
        return column, value

    @staticmethod
    def _exclusive_end(end_date: str) -> str:
        """end_date + 1 day, as it appears in a half-open '< end_date+1' bound."""
        try:
            return (_date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
        except ValueError:
            return end_date

    def _contains_containment_predicate(self, sql: str, column: str, value: str) -> bool:
        """Accepts the composite-column containment form rendered by the
        deterministic builder: ``',' + REPLACE(<col>, ', ', ',') + ',' LIKE
        N'%,<value>,%'`` (and simpler ``<col> LIKE N'%<value>%'`` variants)."""
        stripped = value.strip().strip(",").strip()
        escaped_value = re.escape(stripped.replace("'", "''"))
        return bool(
            re.search(
                rf"\b{re.escape(column)}\b.{{0,60}}?LIKE\s*N?'%[^']*{escaped_value}[^']*%'",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
        )

    def _contains_filter_predicate(self, sql: str, column: str, value: str) -> bool:
        escaped_value = re.escape(value.replace("'", "''"))
        if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
            literal = rf"(?:N?'{escaped_value}'|{escaped_value})"
        else:
            unicode_prefix = "N" if any(ord(character) > 127 for character in value) else "N?"
            literal = rf"{unicode_prefix}'{escaped_value}'"
        return bool(
            re.search(
                rf"\b{re.escape(column)}\b\s*(?:=\s*|IN\s*\([^)]*?)" + literal,
                sql,
                re.IGNORECASE,
            )
        )

    def _select_clause(self, folded_sql: str) -> str:
        match = re.search(r"select\s+(.*?)\s+from\b", folded_sql, re.DOTALL)
        return match.group(1) if match else ""

    def _period_aggregate_issues(self, sql: str, plan: QueryPlan) -> list[str]:
        if len(plan.periods) != 2:
            return ["period comparison requires exactly two plan periods"]
        try:
            statement = sqlglot.parse_one(sql, read="tsql")
        except sqlglot.errors.ParseError:
            return ["period comparison SQL AST could not be parsed"]

        baseline, current = plan.periods
        issues: list[str] = []
        allowed_bounds = {
            baseline.start_inclusive,
            baseline.end_exclusive,
            current.start_inclusive,
            current.end_exclusive,
        }
        unexpected_dates = sorted(
            {
                str(literal.this)
                for literal in statement.find_all(exp.Literal)
                if literal.is_string
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(literal.this))
                and str(literal.this) not in allowed_bounds
            }
        )
        if unexpected_dates:
            issues.append(
                "period SQL contains date literals outside QueryPlan: "
                + ", ".join(unexpected_dates)
            )
        aliases: dict[str, exp.Expression] = {}
        for alias_expression in statement.find_all(exp.Alias):
            aliases[alias_expression.alias.lower()] = alias_expression.this

        period_specs = (
            ("baseline", baseline.start_inclusive, baseline.end_exclusive),
            ("current", current.start_inclusive, current.end_exclusive),
        )
        for prefix, start, end in period_specs:
            candidates = [
                expression
                for alias, expression in aliases.items()
                if alias.startswith(f"{prefix}_") and alias != f"{prefix}_period_label"
            ]
            matching = [
                expression
                for expression in candidates
                if self._is_conditional_aggregate(expression)
                and self._contains_period_bounds(expression, start, end)
            ]
            if not matching:
                issues.append(
                    f"{prefix} conditional aggregate does not match plan period "
                    f"{start}..< {end}"
                )
        return issues

    def _is_conditional_aggregate(self, expression: exp.Expression) -> bool:
        return any(expression.find_all(exp.Case)) and any(expression.find_all(exp.AggFunc))

    def _contains_period_bounds(self, expression: exp.Expression, start: str, end: str) -> bool:
        literals = {
            str(literal.this) for literal in expression.find_all(exp.Literal) if literal.is_string
        }
        if start not in literals or end not in literals:
            return False
        rendered = expression.sql(dialect="tsql").lower()
        return ">=" in rendered and "<" in rendered

    def _requires_grouping(self, plan: QueryPlan) -> bool:
        if plan.analysis_type == "distinct_count":
            return False
        if plan.aggregation and "distinct" in plan.aggregation.lower():
            return False
        return bool(plan.dimensions) and plan.analysis_type not in (
            "cohort_analysis",
            "period_comparison",
            "baseline_comparison",
            "adaptive_time_comparison",
            "percentage_change",
        )

    def _requires_aggregate_shape(self, plan: QueryPlan) -> bool:
        return bool(
            plan.analysis_type
            and plan.analysis_type not in ("list", "detail")
            and (plan.metrics or plan.aggregation or plan.numerator or plan.denominator)
        )

    def _group_by_contains(self, folded_sql: str, dimension: str) -> bool:
        match = re.search(r"group\s+by\s+(.*?)(?:\border\s+by\b|;|$)", folded_sql, re.DOTALL)
        if not match:
            return False
        return re.search(rf"\b{re.escape(dimension.lower())}\b", match.group(1)) is not None

    def _looks_like_raw_detail_projection(self, folded_sql: str) -> bool:
        select_clause = self._select_clause(folded_sql)
        if not select_clause:
            return False
        # TCKimlikNo/PasaportNo/HastaGSM removed from the view: they are now
        # unknown columns caught by schema validation, not raw-detail markers.
        raw_markers = (
            "hastaadi",
            "hastasoyadi",
            "createddate",
            "bitistarihi",
        )
        has_aggregate = any(
            func in select_clause for func in ("count(", "sum(", "avg(", "min(", "max(")
        )
        return has_aggregate and any(marker in select_clause for marker in raw_markers)
