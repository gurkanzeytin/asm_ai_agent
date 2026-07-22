"""Deterministic sanity checks on executed query results (internal validation).

First iteration of the result-validation foundation: given the QueryPlan that
produced a result and the result itself, a fixed set of rule-based checks flags
suspicious shapes (out-of-range percentages, negative counts, null-heavy
output, missing planned dimensions/metrics, non-chronological trends). Findings
are informational — they never block the pipeline; consumers may surface or log
them. No LLM calls, no extra SQL execution.
"""

import logging
from datetime import date, datetime
from numbers import Number

from pydantic import BaseModel, Field

from app.application_models.workflow_models import QueryResult
from app.planning.models import QueryPlan
from app.semantics.catalog import load_metric_catalog

logger = logging.getLogger(__name__)

_LARGE_RESULT_ROWS = 10_000
_NULL_HEAVY_THRESHOLD = 0.5


class ValidationFinding(BaseModel):
    """One rule violation detected on a query result."""

    check: str = Field(..., description="Rule id, e.g. 'percentage_range'.")
    severity: str = Field(default="warning", description="'warning' or 'error'.")
    detail: str = Field(..., description="Human-readable description of the finding.")


class ResultShapeVerdict(BaseModel):
    """Typed verdict comparing an executed result's column shape against the
    plan's expected result contract (deterministic SQL only — LLM-generated
    SQL has no fixed alias contract to compare against).

    Zero-valued numeric columns are always valid; only column presence is
    checked, never values — a legitimate grouped result with every metric at
    zero must never be flagged invalid.
    """

    valid: bool = True
    reason: str | None = None
    missing_columns: list[str] = Field(default_factory=list)
    unexpected_columns: list[str] = Field(default_factory=list)
    expected_shape: str | None = None
    actual_shape: str | None = None


class ResultValidationReport(BaseModel):
    """Outcome of all result checks; valid means no error-level findings."""

    valid: bool = True
    findings: list[ValidationFinding] = Field(default_factory=list)

    def add(self, check: str, detail: str, severity: str = "warning") -> None:
        self.findings.append(ValidationFinding(check=check, severity=severity, detail=detail))
        if severity == "error":
            self.valid = False


class ResultValidator:
    """Rule-based validation of a query result against its QueryPlan."""

    def validate(
        self,
        result: QueryResult,
        plan: QueryPlan | None = None,
        sql: str = "",
    ) -> ResultValidationReport:
        report = ResultValidationReport()
        try:
            self._check_empty(result, report)
            self._check_large(result, report)
            self._check_null_heavy(result, report)
            self._check_counts_and_percentages(result, plan, report)
            if plan is not None:
                self._check_plan_shape(result, plan, report)
                self._check_chronological_trend(result, plan, report)
                self._check_division_protection(plan, sql, report)
        except Exception as error:  # validation is enrichment: never break the pipeline
            logger.error("Result validation degraded: %s", error)
        return report

    def check_shape(
        self,
        result: QueryResult,
        plan: QueryPlan | None = None,
        expected_aliases: list[str] | None = None,
    ) -> ResultShapeVerdict:
        """Compares the executed result's columns against the deterministic
        SQL's fixed alias contract. Only meaningful for the deterministic
        path — LLM-generated SQL carries no fixed alias contract, so an empty
        `expected_aliases` always yields a trivially valid verdict.
        """
        if not expected_aliases:
            return ResultShapeVerdict(valid=True)

        expected_by_lower = {alias.lower(): alias for alias in expected_aliases}
        actual_by_lower = {column.lower(): column for column in result.columns}
        missing = [
            expected_by_lower[key] for key in expected_by_lower if key not in actual_by_lower
        ]
        unexpected = [
            actual_by_lower[key] for key in actual_by_lower if key not in expected_by_lower
        ]

        expected_shape = "grouped" if plan and plan.dimensions else "scalar"
        has_dimension_column = bool(plan and plan.dimensions) and any(
            d.lower() in actual_by_lower for d in (plan.dimensions if plan else [])
        )
        actual_shape = (
            "grouped"
            if has_dimension_column
            else ("scalar" if len(result.columns) <= 1 else "row")
        )

        if missing:
            return ResultShapeVerdict(
                valid=False,
                reason=f"missing expected columns: {', '.join(missing)}",
                missing_columns=missing,
                unexpected_columns=unexpected,
                expected_shape=expected_shape,
                actual_shape=actual_shape,
            )
        if unexpected:
            return ResultShapeVerdict(
                valid=False,
                reason=f"unexpected columns not in plan: {', '.join(unexpected)}",
                unexpected_columns=unexpected,
                expected_shape=expected_shape,
                actual_shape=actual_shape,
            )
        return ResultShapeVerdict(
            valid=True, expected_shape=expected_shape, actual_shape=actual_shape
        )

    # ── shape checks ─────────────────────────────────────────────────────

    def _check_empty(self, result: QueryResult, report: ResultValidationReport) -> None:
        if result.row_count == 0 or not result.rows:
            report.add("empty_result", "Sorgu hiç satır döndürmedi.")

    def _check_large(self, result: QueryResult, report: ResultValidationReport) -> None:
        if result.row_count > _LARGE_RESULT_ROWS:
            report.add(
                "unexpectedly_large_result",
                f"Sonuç beklenmedik biçimde büyük: {result.row_count} satır.",
            )

    def _check_null_heavy(self, result: QueryResult, report: ResultValidationReport) -> None:
        if not result.rows:
            return
        total = len(result.rows) * max(len(result.columns), 1)
        nulls = sum(
            1 for row in result.rows for column in result.columns if row.get(column) is None
        )
        if total and nulls / total > _NULL_HEAVY_THRESHOLD:
            report.add(
                "null_heavy_result",
                f"Sonucun %{100 * nulls / total:.0f} kadarı NULL değer içeriyor.",
            )

    # ── value checks ─────────────────────────────────────────────────────

    # Percentage-range checks apply ONLY to explicitly rate-typed fields. Count
    # fields (cohort_total_count, completed_count, ...) must never be treated as
    # percentages, whatever the plan's metric types are.
    _RATE_SUFFIXES = ("_rate", "_percentage", "_orani", "_yuzdesi")
    _COUNT_MARKERS = ("count", "sayi", "adet", "total", "toplam", "hacim")
    # percentage_change is unbounded (+250% growth is valid); rate_point_change
    # is a difference of two 0-100 rates, bounded to [-100, 100].
    _UNBOUNDED_CHANGE = {"percentage_change", "absolute_change"}

    def _is_rate_column(self, lowered: str) -> bool:
        if lowered in self._UNBOUNDED_CHANGE or any(
            marker in lowered for marker in self._COUNT_MARKERS
        ):
            return False
        if lowered == "rate_point_change" or lowered.endswith(self._RATE_SUFFIXES):
            return True
        return any(marker in lowered for marker in ("oran", "yuzde", "percent"))

    def _check_counts_and_percentages(
        self,
        result: QueryResult,
        plan: QueryPlan | None,
        report: ResultValidationReport,
    ) -> None:
        for column in result.columns:
            lowered = column.lower()
            looks_percentage = self._is_rate_column(lowered)
            looks_count = any(marker in lowered for marker in ("sayi", "adet", "count", "toplam"))
            for row in result.rows:
                value = row.get(column)
                if not isinstance(value, Number) or isinstance(value, bool):
                    continue
                lower_bound = -100.0 if lowered == "rate_point_change" else 0.0
                if looks_percentage and not lower_bound <= float(value) <= 100:
                    report.add(
                        "percentage_range",
                        f"'{column}' yüzde kolonu beklenen aralık dışında: {value}",
                        severity="error",
                    )
                    break
                if looks_count and float(value) < 0:
                    report.add(
                        "non_negative_count",
                        f"'{column}' sayım kolonu negatif değer içeriyor: {value}",
                        severity="error",
                    )
                    break

    # ── plan conformance checks ──────────────────────────────────────────

    def _check_plan_shape(
        self, result: QueryResult, plan: QueryPlan, report: ResultValidationReport
    ) -> None:
        lowered_columns = {column.lower() for column in result.columns}
        for dimension in plan.dimensions:
            if result.rows and dimension.lower() not in lowered_columns:
                report.add(
                    "missing_expected_dimension",
                    f"Planlanan boyut '{dimension}' sonuç kolonlarında yok.",
                )
        if plan.metrics and result.rows:
            has_numeric = any(
                isinstance(row.get(column), Number) and not isinstance(row.get(column), bool)
                for row in result.rows[:5]
                for column in result.columns
            )
            if not has_numeric:
                report.add(
                    "missing_expected_metric",
                    "Plan metrik içeriyor ama sonuçta sayısal kolon bulunamadı.",
                )

    def _check_chronological_trend(
        self, result: QueryResult, plan: QueryPlan, report: ResultValidationReport
    ) -> None:
        if plan.analysis_type != "time_trend" and not plan.grouping_granularity:
            return
        time_column = self._time_bucket_column(result)
        if time_column is None:
            return
        values = [row.get(time_column) for row in result.rows if row.get(time_column) is not None]
        comparable = [value for value in values if isinstance(value, (str, date, datetime))]
        if len(comparable) >= 2 and comparable != sorted(comparable):
            report.add(
                "chronological_order_for_trend",
                f"Trend sonucu '{time_column}' kolonuna göre kronolojik sıralı değil.",
            )

    def _time_bucket_column(self, result: QueryResult) -> str | None:
        for column in result.columns:
            lowered = column.lower()
            markers = ("ay", "gun", "hafta", "yil", "tarih", "date", "month", "day", "week", "year")
            if any(marker in lowered for marker in markers):
                return column
        return None

    def _check_division_protection(
        self, plan: QueryPlan, sql: str, report: ResultValidationReport
    ) -> None:
        if not sql or "/" not in sql:
            return
        needs_protection = bool(plan.numerator and plan.denominator)
        if needs_protection and "nullif" not in sql.lower():
            report.add(
                "division_by_zero_protection",
                "Oran hesaplayan SQL NULLIF ile sıfıra bölme koruması içermiyor.",
            )

    def _percentage_metric_ids(self) -> set[str]:
        try:
            return {
                metric.id
                for metric in load_metric_catalog().metrics
                if metric.result_type == "percentage"
            }
        except Exception:
            return set()
