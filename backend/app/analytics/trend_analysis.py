"""Trailing-bucket completeness and endpoint/slope trend semantics.

Pure functions over an already time-bucketed SQL result (period labels +
numeric values). No SQL, no I/O, no LLM — mirrors ``app.analytics.calculators``
in determinism. Reconciles the two independent trend statistics
(``calculators.difference`` = first-vs-last, ``calculators.trend_direction`` =
half-vs-half mean) into one coherent verdict, computed only over periods whose
calendar bucket has fully elapsed as of ``today``.
"""

import calendar
import statistics
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict

# Relative change below this fraction counts as "flat" — mirrors
# calculators._TREND_STABILITY_THRESHOLD so endpoint/slope direction and the
# legacy half-vs-half trend_direction agree on what "stable" means.
_STABILITY_THRESHOLD = 0.05


def _to_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    if len(text) == 7:  # "YYYY-MM" (month-grain label with no day component)
        text += "-01"
    return date.fromisoformat(text)


def bucket_end_date(period_start: date, grain: str) -> date:
    """Last calendar day covered by a bucket of the given grain."""
    if grain == "day":
        return period_start
    if grain == "week":
        return period_start + timedelta(days=6)
    if grain == "quarter":
        end_month_index = period_start.month + 2
        end_year = period_start.year + (end_month_index - 1) // 12
        end_month = ((end_month_index - 1) % 12) + 1
        last_day = calendar.monthrange(end_year, end_month)[1]
        return date(end_year, end_month, last_day)
    if grain == "year":
        return date(period_start.year, 12, 31)
    # month (default): matches DeterministicSQLBuilder's default grain.
    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
    return date(period_start.year, period_start.month, last_day)


class PartialPeriodInfo(BaseModel):
    """Which returned periods are still in progress as of ``today``."""

    model_config = ConfigDict(frozen=True)

    partial_periods: list[str] = []
    first_period_complete: bool = True
    last_period_complete: bool = True
    comparison_excluded_partial_period: bool = False
    excluded_periods: list[str] = []


def detect_partial_periods(
    period_starts: list[str], grain: str, today: date
) -> PartialPeriodInfo:
    """Flags any bucket whose calendar range has not fully elapsed yet.

    In an ascending chronologically ordered series only the trailing bucket
    can legitimately be partial (all earlier buckets are already in the
    past) — this checks every bucket generically rather than hard-coding the
    last index, so it stays correct regardless of series length or order.
    """
    if not period_starts:
        return PartialPeriodInfo()
    parsed = [_to_date(value) for value in period_starts]
    partial_indexes = [
        index
        for index, start in enumerate(parsed)
        if start <= today <= bucket_end_date(start, grain)
    ]
    partial_labels = [period_starts[index] for index in partial_indexes]
    first_complete = 0 not in partial_indexes
    last_complete = (len(parsed) - 1) not in partial_indexes
    excluded = [period_starts[-1]] if not last_complete else []
    return PartialPeriodInfo(
        partial_periods=partial_labels,
        first_period_complete=first_complete,
        last_period_complete=last_complete,
        comparison_excluded_partial_period=bool(excluded),
        excluded_periods=excluded,
    )


class TrendMetrics(BaseModel):
    """Endpoint (first-vs-last) and slope (overall) trend verdicts, computed
    only over complete/comparable periods — the two statistics that, computed
    independently over the FULL series (including a partial trailing bucket),
    previously produced contradictory rules (e.g. DECLINING + POSITIVE_TREND
    firing together)."""

    model_config = ConfigDict(frozen=True)

    endpoint_change: float | None = None
    endpoint_percentage_change: float | None = None
    endpoint_direction: str | None = None  # upward | downward | flat
    slope: float | None = None
    slope_direction: str | None = None  # upward | downward | flat
    # AI-INTELLIGENCE-018 (item 7): adjacent-pair monotonicity — independent
    # of endpoint_direction/slope_direction, which both only ever compare two
    # aggregate summaries (first-vs-last, overall regression) and can agree
    # with each other while the series still fluctuated in between (e.g.
    # [12, 15, 9, 13, 13, 19]: endpoint/slope both "upward", yet 15->9 is a
    # clear drop) — monotonic_up | monotonic_down | non_monotonic | flat.
    monotonicity: str = "insufficient_data"
    trend_consistency: str = "insufficient_data"
    volatility: float | None = None
    first_comparable_period: str | None = None
    last_comparable_period: str | None = None
    comparable_period_count: int = 0
    partial_periods: list[str] = []
    first_period_complete: bool = True
    last_period_complete: bool = True
    comparison_excluded_partial_period: bool = False
    excluded_periods: list[str] = []


def _relative_direction(delta: float, baseline: float) -> str:
    if baseline == 0:
        if delta == 0:
            return "flat"
        return "upward" if delta > 0 else "downward"
    change = delta / abs(baseline)
    if abs(change) <= _STABILITY_THRESHOLD:
        return "flat"
    return "upward" if change > 0 else "downward"


def _monotonicity(values: list[float]) -> str:
    """Classifies adjacent-pair (non-zero) direction agreement.

    'monotonic_up'/'monotonic_down' require EVERY non-zero adjacent change to
    point the same way (a strict rule, deliberately — see module/item 7
    docstring: no partial-majority relaxation implemented). A series with no
    non-zero change at all is 'flat'; any mix of up/down changes is
    'non_monotonic'.
    """
    diffs = [b - a for a, b in zip(values, values[1:], strict=False)]
    nonzero = [d for d in diffs if d != 0]
    if not nonzero:
        return "flat"
    if all(d > 0 for d in nonzero):
        return "monotonic_up"
    if all(d < 0 for d in nonzero):
        return "monotonic_down"
    return "non_monotonic"


def _linear_slope(values: list[float]) -> float:
    """Least-squares slope of ``values`` against their index position."""
    n = len(values)
    xs = list(range(n))
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(values)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=True))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def compute_trend_metrics(
    labels: list[str], values: list[float], grain: str | None, today: date
) -> TrendMetrics:
    """Builds the reconciled trend verdict for an ordered (label, value) series."""
    resolved_grain = grain or "month"
    partial = detect_partial_periods(labels, resolved_grain, today)
    excluded_set = set(partial.excluded_periods)
    comparable = [
        (label, value)
        for label, value in zip(labels, values, strict=True)
        if label not in excluded_set
    ]
    comparable_period_count = len(comparable)

    if comparable_period_count < 2:
        return TrendMetrics(
            comparable_period_count=comparable_period_count,
            first_comparable_period=comparable[0][0] if comparable else None,
            last_comparable_period=comparable[-1][0] if comparable else None,
            trend_consistency="insufficient_data",
            **partial.model_dump(),
        )

    comparable_labels = [label for label, _ in comparable]
    comparable_values = [value for _, value in comparable]

    first_value, last_value = comparable_values[0], comparable_values[-1]
    endpoint_change = round(last_value - first_value, 2)
    endpoint_percentage_change = (
        round(endpoint_change / abs(first_value) * 100, 2) if first_value != 0 else None
    )
    endpoint_direction = _relative_direction(endpoint_change, first_value)

    slope = _linear_slope(comparable_values)
    mean_value = statistics.fmean(comparable_values)
    slope_direction = _relative_direction(slope, mean_value)

    # AI-INTELLIGENCE-018 (item 7): trend_consistency is now derived purely
    # from adjacent-pair MONOTONICITY, never from endpoint/slope agreement —
    # two aggregate two-point comparisons can agree ("upward") on a series
    # that still fluctuated wildly in between. endpoint_direction/
    # slope_direction remain independent, separately reported fields.
    monotonicity = _monotonicity(comparable_values)
    if monotonicity == "flat":
        consistency = "flat"
    elif monotonicity == "monotonic_up":
        consistency = "consistent_upward"
    elif monotonicity == "monotonic_down":
        consistency = "consistent_downward"
    else:
        consistency = "mixed_or_fluctuating"

    volatility = None
    if mean_value != 0:
        volatility = round(statistics.pstdev(comparable_values) / abs(mean_value) * 100, 2)

    return TrendMetrics(
        endpoint_change=endpoint_change,
        endpoint_percentage_change=endpoint_percentage_change,
        endpoint_direction=endpoint_direction,
        slope=round(slope, 4),
        slope_direction=slope_direction,
        monotonicity=monotonicity,
        trend_consistency=consistency,
        volatility=volatility,
        first_comparable_period=comparable_labels[0],
        last_comparable_period=comparable_labels[-1],
        comparable_period_count=comparable_period_count,
        **partial.model_dump(),
    )
