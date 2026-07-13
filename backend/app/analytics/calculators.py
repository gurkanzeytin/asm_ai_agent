"""Deterministic metric calculators for the Analytics Engine.

Pure functions over numeric sequences and (label, value) pairs. No LLM, no I/O.
New calculators are registered in ``CALCULATORS`` so the engine and future
analytics can discover them by name.
"""

import statistics
from collections.abc import Callable, Sequence

Number = float | int
LabeledValue = tuple[str, float]

# Relative half-over-half change below this threshold counts as a stable trend.
_TREND_STABILITY_THRESHOLD = 0.05


def _round(value: float) -> float:
    return round(float(value), 2)


def total(values: Sequence[Number]) -> float:
    return _round(sum(values)) if values else 0.0


def average(values: Sequence[Number]) -> float | None:
    if not values:
        return None
    return _round(statistics.fmean(values))


def median(values: Sequence[Number]) -> float | None:
    if not values:
        return None
    return _round(statistics.median(values))


def minimum(values: Sequence[Number]) -> float | None:
    return _round(min(values)) if values else None


def maximum(values: Sequence[Number]) -> float | None:
    return _round(max(values)) if values else None


def count(values: Sequence[Number]) -> int:
    return len(values)


def difference(values: Sequence[Number]) -> float | None:
    """Absolute change between the first and last value of an ordered series."""
    if len(values) < 2:
        return None
    return _round(values[-1] - values[0])


def percentage_difference(values: Sequence[Number]) -> float | None:
    """Percentage change between the first and last value of an ordered series."""
    if len(values) < 2 or values[0] == 0:
        return None
    return _round((values[-1] - values[0]) / abs(values[0]) * 100)


def growth_rate(values: Sequence[Number]) -> float | None:
    """Growth rate over an ordered series (first → last, percent)."""
    return percentage_difference(values)


def trend_direction(values: Sequence[Number]) -> str | None:
    """Classifies an ordered series as 'upward', 'downward', or 'stable'.

    Compares the mean of the second half against the mean of the first half;
    changes within ±5% are considered stable. Deterministic and robust to
    single-point noise, unlike a first-vs-last comparison.
    """
    if len(values) < 2:
        return None
    midpoint = len(values) // 2
    first_half = statistics.fmean(values[:midpoint] or values[:1])
    second_half = statistics.fmean(values[midpoint:])
    if first_half == 0:
        if second_half == 0:
            return "stable"
        return "upward" if second_half > 0 else "downward"
    change = (second_half - first_half) / abs(first_half)
    if abs(change) <= _TREND_STABILITY_THRESHOLD:
        return "stable"
    return "upward" if change > 0 else "downward"


def rank(items: Sequence[LabeledValue], descending: bool = True) -> list[LabeledValue]:
    """Sorts (label, value) pairs by value; ties broken by label for determinism."""
    return sorted(items, key=lambda item: (-item[1] if descending else item[1], item[0]))


def top_n(items: Sequence[LabeledValue], n: int) -> list[LabeledValue]:
    return rank(items, descending=True)[: max(n, 0)]


def bottom_n(items: Sequence[LabeledValue], n: int) -> list[LabeledValue]:
    return rank(items, descending=False)[: max(n, 0)]


def largest_change(labels: Sequence[str], values: Sequence[Number]) -> str | None:
    """Label of the period with the largest absolute step from its predecessor."""
    if len(values) < 2 or len(labels) != len(values):
        return None
    deltas = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    return str(labels[deltas.index(max(deltas)) + 1])


# Registry for discoverability and future extension (e.g. correlation, forecast).
CALCULATORS: dict[str, Callable] = {
    "total": total,
    "average": average,
    "median": median,
    "minimum": minimum,
    "maximum": maximum,
    "count": count,
    "difference": difference,
    "percentage_difference": percentage_difference,
    "growth_rate": growth_rate,
    "trend_direction": trend_direction,
    "rank": rank,
    "top_n": top_n,
    "bottom_n": bottom_n,
    "largest_change": largest_change,
}
