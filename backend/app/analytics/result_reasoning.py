"""Post-execution deterministic result reasoning.

The reasoner consumes normalized, typed analytical results when available and
falls back to generic numeric-column reasoning for legacy LLM SQL shapes. It
never raises and never calls an LLM.
"""

import logging
from numbers import Number

from pydantic import BaseModel, Field

from app.application_models.workflow_models import QueryResult
from app.planning.models import QueryPlan
from app.reporting.presentation import (
    STATUS_LABELS_TR,
    format_number,
    format_percent,
)

logger = logging.getLogger(__name__)

MAX_FINDINGS = 3

_COUNT_MARKERS = ("sayi", "adet", "count", "toplam", "hacim")
_RATE_MARKERS = ("oran", "yuzde", "rate", "percent", "pay")
_PERIOD_MARKERS = (
    "donem",
    "period",
    "current",
    "onceki",
    "previous",
    "baseline",
    "bu_",
    "gecen",
    "simdiki",
)


class ReasoningOutcome(BaseModel):
    """Digested analytical reading of a query result."""

    findings: list[str] = Field(default_factory=list)
    low_sample_groups: list[str] = Field(default_factory=list)
    baseline_delta: float | None = Field(default=None)
    summarized: bool = Field(default=False)
    assumptions: list[str] = Field(default_factory=list)


class ResultReasoner:
    """Rule-based reasoning over plan + result; never raises, never calls an LLM."""

    def reason(
        self,
        result: QueryResult,
        plan: QueryPlan | None = None,
        result_schema: str | None = None,
        warnings: list[str] | None = None,
    ) -> ReasoningOutcome:
        outcome = ReasoningOutcome(assumptions=list(plan.assumptions) if plan else [])
        try:
            for warning in warnings or []:
                if warning != "empty result":
                    outcome.findings.append(f"Sonuç şekli uyarısı: {warning}.")
            if not result.rows:
                outcome.findings.append(
                    "Sorgu sonuç döndürmedi; dönem veya filtre daraltıcı olabilir."
                )
                return outcome
            if result_schema and self._typed_summary(result, result_schema, outcome):
                outcome.findings = outcome.findings[:MAX_FINDINGS]
                return outcome
            numeric_columns = self._numeric_columns(result)
            self._flag_low_samples(result, plan, numeric_columns, outcome)
            self._baseline_delta(result, plan, numeric_columns, outcome)
            self._top_groups(result, plan, numeric_columns, outcome)
            if result.row_count > 20:
                outcome.summarized = True
                outcome.findings.append(
                    f"{result.row_count} satır özetlendi; en anlamlı bulgular öne çıkarıldı."
                )
            outcome.findings = outcome.findings[:MAX_FINDINGS]
        except Exception as error:
            logger.error("Result reasoning degraded: %s", error)
            if not outcome.findings:
                outcome.findings.append(
                    "Sonuçlar deterministik olarak özetlenemedi; sonuç şekli beklenenden farklı."
                )
        return outcome

    def _typed_summary(
        self,
        result: QueryResult,
        schema_name: str,
        outcome: ReasoningOutcome,
    ) -> bool:
        row = result.rows[0]
        if schema_name == "CohortResult":
            total = row.get("cohort_total_count")
            outcome.findings.append(
                f"Son dakika alınan {format_number(total)} randevunun "
                f"{format_percent(row.get('completed_rate'))} kadarı gerçekleşti; "
                f"gelmeme oranı {format_percent(row.get('no_show_rate'))}."
            )
            secondary = []
            for prefix in ("checked_in", "in_progress", "waiting"):
                rate = row.get(f"{prefix}_rate")
                if isinstance(rate, Number):
                    secondary.append(
                        f"{STATUS_LABELS_TR[prefix].lower()} {format_percent(rate)}"
                    )
            if secondary:
                outcome.findings.append(
                    "Kalan durumlar: " + ", ".join(secondary) + "."
                )
            self._check_rate_sum(row, outcome)
            return True
        if schema_name == "AnomalyResult":
            return self._anomaly_summary(result, outcome)
        if schema_name == "PeriodComparisonResult":
            current = row.get("current_period_count") or row.get("current_rate")
            baseline = row.get("baseline_period_count") or row.get("baseline_rate")
            absolute = row.get("absolute_change")
            percentage = row.get("percentage_change") or row.get("rate_point_change")
            outcome.baseline_delta = float(percentage) if isinstance(percentage, Number) else None
            outcome.findings.append(
                f"Mevcut dönem {format_number(current)}, önceki dönem {format_number(baseline)}; "
                f"sayısal değişim {format_number(absolute)}, "
                f"yüzdesel değişim {format_percent(percentage)}."
            )
            return True
        if schema_name == "VarianceResult":
            outcome.findings.append(
                f"{format_number(row.get('group_count'))} grup için ortalama "
                f"{format_number(row.get('average_appointments'))}, en düşük "
                f"{format_number(row.get('minimum_appointments'))}, en yüksek "
                f"{format_number(row.get('maximum_appointments'))}; "
                f"en yüksek/ortalama oranı {self._fmt(row.get('max_to_average_ratio'))}."
            )
            outcome.findings.append(
                f"İlk %10 grubun payı {format_percent(row.get('top_10_percent_share'))}."
            )
            return True
        return False

    def _check_rate_sum(self, row: dict, outcome: ReasoningOutcome) -> None:
        """Verified status rates must cover ~100% of the cohort."""
        rates = [
            row.get(f"{prefix}_rate")
            for prefix in ("completed", "checked_in", "no_show", "in_progress", "waiting")
        ]
        numeric = [float(r) for r in rates if isinstance(r, Number) and not isinstance(r, bool)]
        if len(numeric) == 5:
            total = sum(numeric)
            if abs(total - 100.0) > 1.5:
                outcome.findings.append(
                    f"Durum oranlarının toplamı {format_percent(total)}; "
                    "beklenen %100'den anlamlı biçimde farklı."
                )

    def _anomaly_summary(self, result: QueryResult, outcome: ReasoningOutcome) -> bool:
        """Anomaly rows: never force a winner when no group shows an increase."""
        rows = [
            row for row in result.rows
            if isinstance(row.get("rate_point_change"), Number)
        ]
        if not rows:
            return False
        label_column = next(
            (c for c in result.columns if not any(
                m in c.lower() for m in ("count", "rate", "change"))),
            None,
        )
        increased = [row for row in rows if float(row["rate_point_change"]) > 0]
        if not increased:
            outcome.findings.append(
                "İncelenen dönemde hiçbir grupta aranan oranda artış tespit edilmedi."
            )
            return True
        top = max(increased, key=lambda row: float(row["rate_point_change"]))
        label = top.get(label_column, "?") if label_column else "?"
        outcome.findings.append(
            f"En belirgin artış {label} grubunda: oran farkı "
            f"{format_percent(top.get('rate_point_change'))} puan."
        )
        if len(increased) > 1:
            outcome.findings.append(
                f"Toplam {format_number(len(increased))} grupta artış görüldü."
            )
        return True

    def _numeric_columns(self, result: QueryResult) -> list[str]:
        columns = []
        for column in result.columns:
            for row in result.rows[:5]:
                value = row.get(column)
                if isinstance(value, Number) and not isinstance(value, bool):
                    columns.append(column)
                    break
        return columns

    def _label_column(self, result: QueryResult, numeric_columns: list[str]) -> str | None:
        for column in result.columns:
            if column not in numeric_columns:
                return column
        return None

    def _count_column(self, numeric_columns: list[str]) -> str | None:
        for column in numeric_columns:
            if any(marker in column.lower() for marker in _COUNT_MARKERS):
                return column
        return numeric_columns[0] if numeric_columns else None

    def _rate_column(self, numeric_columns: list[str]) -> str | None:
        for column in numeric_columns:
            if any(marker in column.lower() for marker in _RATE_MARKERS):
                return column
        return None

    def _flag_low_samples(
        self,
        result: QueryResult,
        plan: QueryPlan | None,
        numeric_columns: list[str],
        outcome: ReasoningOutcome,
    ) -> None:
        minimum = plan.minimum_sample_size if plan and plan.minimum_sample_size else None
        if not minimum:
            return
        count_column = self._count_column(numeric_columns)
        label_column = self._label_column(result, numeric_columns)
        if not count_column:
            return
        for row in result.rows:
            value = row.get(count_column)
            if isinstance(value, Number) and not isinstance(value, bool) and value < minimum:
                label = str(row.get(label_column, "?")) if label_column else "?"
                outcome.low_sample_groups.append(label)
        if outcome.low_sample_groups:
            shown = ", ".join(outcome.low_sample_groups[:5])
            outcome.findings.append(
                f"Düşük örneklem ({minimum} altı): {shown}; oranlar yanıltıcı olabilir."
            )

    def _baseline_delta(
        self,
        result: QueryResult,
        plan: QueryPlan | None,
        numeric_columns: list[str],
        outcome: ReasoningOutcome,
    ) -> None:
        if plan is None or not (plan.baseline_period or plan.comparisons):
            return
        period_columns = [
            column
            for column in numeric_columns
            if any(marker in column.lower() for marker in _PERIOD_MARKERS)
        ]
        current = baseline = None
        if len(period_columns) >= 2 and len(result.rows) == 1:
            row = result.rows[0]
            current, baseline = row.get(period_columns[0]), row.get(period_columns[1])
        elif len(result.rows) == 2 and numeric_columns:
            metric_column = self._count_column(numeric_columns)
            current = result.rows[0].get(metric_column)
            baseline = result.rows[1].get(metric_column)
        if (
            isinstance(current, Number)
            and isinstance(baseline, Number)
            and not isinstance(current, bool)
            and not isinstance(baseline, bool)
            and float(baseline) != 0
        ):
            delta = 100.0 * (float(current) - float(baseline)) / float(baseline)
            outcome.baseline_delta = round(delta, 1)
            direction = "arttı" if delta > 0 else "azaldı"
            delta_text = str(abs(outcome.baseline_delta)).replace(".", ",")
            outcome.findings.append(f"Önceki döneme göre %{delta_text} {direction}.")

    def _top_groups(
        self,
        result: QueryResult,
        plan: QueryPlan | None,
        numeric_columns: list[str],
        outcome: ReasoningOutcome,
    ) -> None:
        if len(result.rows) < 2:
            return
        label_column = self._label_column(result, numeric_columns)
        metric_column = self._rate_column(numeric_columns) or self._count_column(numeric_columns)
        if not label_column or not metric_column:
            return
        valid_rows = [
            row
            for row in result.rows
            if isinstance(row.get(metric_column), Number)
            and not isinstance(row.get(metric_column), bool)
        ]
        if len(valid_rows) < 2:
            return
        ranked = sorted(valid_rows, key=lambda row: float(row[metric_column]), reverse=True)
        top, bottom = ranked[0], ranked[-1]
        top_text = self._fmt(top.get(metric_column))
        bottom_text = self._fmt(bottom.get(metric_column))
        outcome.findings.append(
            f"En yüksek değer {top.get(label_column)} grubunda ({top_text}); "
            f"en düşük {bottom.get(label_column)} ({bottom_text})."
        )
        top_value, bottom_value = float(top[metric_column]), float(bottom[metric_column])
        if bottom_value > 0 and top_value / bottom_value >= 3:
            outcome.findings.append(
                f"Gruplar arasında belirgin fark var: en yüksek değer en düşüğün "
                f"{self._fmt(top_value / bottom_value)} katı."
            )

    def _fmt(self, value) -> str:
        if value is None:
            return "yok"
        if isinstance(value, Number) and not isinstance(value, bool):
            return f"{float(value):.1f}".rstrip("0").rstrip(".")
        return str(value)
