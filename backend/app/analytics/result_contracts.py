"""Typed result contracts and normalization for deterministic analytical SQL."""

# ruff: noqa: E501

from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from app.application_models.workflow_models import QueryResult

if TYPE_CHECKING:
    from app.planning.models import QueryPlan


class NormalizedResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_name: str
    columns: list[str]
    rows: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


class CountResult(BaseModel):
    appointment_count: int | float | None = None


class DistributionResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class RatioResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class PeriodComparisonResult(BaseModel):
    """Comparison contract: BOTH periods must be present, or the comparison
    presentation is not rendered (single values never reach the template)."""

    current_period_label: str | None = None
    baseline_period_label: str | None = None
    current_period_count: float | None = None
    baseline_period_count: float | None = None
    absolute_change: float | None = None
    percentage_change: float | None = None

    def is_complete(self) -> bool:
        return (
            self.current_period_count is not None
            and self.baseline_period_count is not None
            and self.absolute_change is not None
        )


class EntityComparisonResult(BaseModel):
    """Two-entity comparison contract ("Kardiyoloji ile Psikiyatri"): both
    conditional counts must be present or the comparison presentation is not
    rendered (mirrors PeriodComparisonResult's completeness rule)."""

    current_entity_label: str | None = None
    baseline_entity_label: str | None = None
    comparison_total_count: float | None = None
    current_entity_count: float | None = None
    baseline_entity_count: float | None = None
    absolute_change: float | None = None
    percentage_change: float | None = None

    def is_complete(self) -> bool:
        return (
            self.current_entity_count is not None
            and self.baseline_entity_count is not None
            and self.absolute_change is not None
        )


class CohortResult(BaseModel):
    """Full verified-status distribution of the cohort.

    The view carries exactly five RandevuDurumu values; there is no 'İptal',
    so this contract has no cancelled fields.
    """

    cohort_total_count: float | None = None
    completed_count: float | None = None
    completed_rate: float | None = None
    checked_in_count: float | None = None
    checked_in_rate: float | None = None
    no_show_count: float | None = None
    no_show_rate: float | None = None
    in_progress_count: float | None = None
    in_progress_rate: float | None = None
    waiting_count: float | None = None
    waiting_rate: float | None = None


class AnomalyResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class VarianceResult(BaseModel):
    group_count: float | None = None
    total_appointments: float | None = None
    average_appointments: float | None = None
    minimum_appointments: float | None = None
    maximum_appointments: float | None = None
    max_to_average_ratio: float | None = None
    top_10_percent_share: float | None = None


class TrendResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


CONTRACT_ALIASES: dict[str, set[str]] = {
    "CohortResult": set(CohortResult.model_fields),
    # Labels are presentation extras; the numeric core is the contract.
    "PeriodComparisonResult": {
        "current_period_count", "baseline_period_count",
        "absolute_change", "percentage_change",
    },
    "EntityComparisonResult": {
        "current_entity_count", "baseline_entity_count",
        "absolute_change", "percentage_change",
    },
    "VarianceResult": set(VarianceResult.model_fields),
}


class TypedResultNormalizer:
    """Normalizes result values and validates deterministic aliases."""

    def normalize(
        self,
        result: QueryResult,
        *,
        plan: "QueryPlan | None" = None,
        schema_name: str | None = None,
        expected_aliases: list[str] | None = None,
    ) -> NormalizedResult:
        rows = [
            {str(column): self._normalize_value(value) for column, value in row.items()}
            for row in result.rows
        ]
        columns = list(rows[0].keys()) if rows else list(result.columns)
        warnings: list[str] = []
        expected = set(expected_aliases or [])
        if expected and rows:
            missing = sorted(expected - set(columns))
            if missing:
                warnings.append(f"missing expected aliases: {', '.join(missing)}")
        if not rows:
            warnings.append("empty result")
        selected_schema = schema_name or self._schema_from_plan(plan)
        self._validate_shape(selected_schema, rows, warnings)
        return NormalizedResult(
            schema_name=selected_schema,
            columns=columns,
            rows=rows,
            warnings=warnings,
        )

    def as_query_result(self, result: QueryResult, normalized: NormalizedResult) -> QueryResult:
        return result.model_copy(
            update={
                "columns": normalized.columns,
                "rows": normalized.rows,
                "row_count": len(normalized.rows),
            }
        )

    def _normalize_value(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        return value

    def _schema_from_plan(self, plan: "QueryPlan | None") -> str:
        if plan is None:
            return "DistributionResult"
        mapping = {
            "cohort_analysis": "CohortResult",
            "anomaly_comparison": "AnomalyResult",
            "variance_analysis": "VarianceResult",
            "period_comparison": "PeriodComparisonResult",
            "baseline_comparison": "PeriodComparisonResult",
            "comparison": "EntityComparisonResult",
            "time_trend": "TrendResult",
            "ratio": "RatioResult",
            "percentage": "RatioResult",
        }
        return mapping.get(plan.analysis_type or "", "DistributionResult")

    def _validate_shape(
        self, schema_name: str, rows: list[dict[str, Any]], warnings: list[str]
    ) -> None:
        if not rows:
            return
        row = rows[0]
        expected = CONTRACT_ALIASES.get(schema_name)
        if expected:
            missing = sorted(expected - set(row))
            if missing:
                warnings.append(f"unexpected result shape for {schema_name}: missing {', '.join(missing)}")
        try:
            if schema_name == "CohortResult":
                CohortResult(**row)
            elif schema_name == "PeriodComparisonResult":
                PeriodComparisonResult(**row)
            elif schema_name == "EntityComparisonResult":
                EntityComparisonResult(**row)
            elif schema_name == "VarianceResult":
                VarianceResult(**row)
        except Exception as error:
            warnings.append(f"typed result validation failed: {error}")
