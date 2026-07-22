import logging
import re

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
            if date_filter.start_date not in folded_sql and date_filter.end_date not in folded_sql:
                missing.append(
                    f"date filter {date_filter.start_date}..{date_filter.end_date} "
                    f"('{date_filter.expression}')"
                )

        if plan.department_filter:
            folded_department = plan.department_filter.translate(_FOLD_TABLE).lower()
            if folded_department not in folded_sql:
                missing.append(f"department filter '{plan.department_filter}'")

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
