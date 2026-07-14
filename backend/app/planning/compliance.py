import logging
import re

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

    def check(self, sql: str, plan: QueryPlan) -> ComplianceResult:
        folded_sql = sql.translate(_FOLD_TABLE).lower()
        missing: list[str] = []

        for date_filter in plan.date_filters:
            if (
                date_filter.start_date not in folded_sql
                and date_filter.end_date not in folded_sql
            ):
                missing.append(
                    f"date filter {date_filter.start_date}..{date_filter.end_date} "
                    f"('{date_filter.expression}')"
                )

        if plan.department_filter:
            folded_department = plan.department_filter.translate(_FOLD_TABLE).lower()
            if folded_department not in folded_sql:
                missing.append(f"department filter '{plan.department_filter}'")

        if plan.aggregation:
            marker = _AGGREGATES.get(plan.aggregation, "")
            if marker and marker not in folded_sql:
                missing.append(f"aggregation {plan.aggregation}")

        if plan.ranking and "order by" not in folded_sql:
            missing.append(f"ranking (ORDER BY ... {plan.ranking})")

        if plan.limit and not re.search(rf"\blimit\s+{plan.limit}\b", folded_sql):
            missing.append(f"LIMIT {plan.limit}")

        if plan.projection:
            select_clause = self._select_clause(folded_sql)
            if select_clause and plan.projection[0].lower() not in select_clause:
                missing.append(f"projection column {plan.projection[0]}")

        for step in plan.join_path:
            for table in (step.from_table, step.to_table):
                if not re.search(rf"\b{re.escape(table.lower())}\b", folded_sql):
                    missing.append(f"join table {table}")

        result = ComplianceResult(compliant=not missing, missing=sorted(set(missing)))
        logger.info(
            "Plan compliance check: compliant=%s missing=%s",
            result.compliant,
            result.missing or "none",
            extra={"compliant": result.compliant, "missing_constraints": result.missing},
        )
        return result

    def _select_clause(self, folded_sql: str) -> str:
        match = re.search(r"select\s+(.*?)\s+from\b", folded_sql, re.DOTALL)
        return match.group(1) if match else ""
