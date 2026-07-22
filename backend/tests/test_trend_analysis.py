"""Unit tests for app.analytics.trend_analysis — bucket completeness detection
and the reconciled endpoint/slope trend verdict."""

from datetime import date

from app.analytics.trend_analysis import (
    bucket_end_date,
    compute_trend_metrics,
    detect_partial_periods,
)

# ── bucket_end_date ─────────────────────────────────────────────────────────


def test_bucket_end_date_day():
    assert bucket_end_date(date(2026, 7, 15), "day") == date(2026, 7, 15)


def test_bucket_end_date_week():
    assert bucket_end_date(date(2026, 7, 13), "week") == date(2026, 7, 19)


def test_bucket_end_date_month():
    assert bucket_end_date(date(2026, 2, 1), "month") == date(2026, 2, 28)


def test_bucket_end_date_month_leap_year():
    assert bucket_end_date(date(2028, 2, 1), "month") == date(2028, 2, 29)


def test_bucket_end_date_quarter_crossing_year():
    assert bucket_end_date(date(2026, 11, 1), "quarter") == date(2027, 1, 31)


def test_bucket_end_date_year():
    assert bucket_end_date(date(2026, 1, 1), "year") == date(2026, 12, 31)


# ── detect_partial_periods ──────────────────────────────────────────────────


def test_trailing_month_within_today_is_partial():
    info = detect_partial_periods(
        ["2026-05-01", "2026-06-01", "2026-07-01"], "month", date(2026, 7, 15)
    )
    assert info.excluded_periods == ["2026-07-01"]
    assert info.comparison_excluded_partial_period is True
    assert info.last_period_complete is False
    assert info.first_period_complete is True


def test_complete_historical_month_not_excluded():
    info = detect_partial_periods(["2026-05-01", "2026-06-01"], "month", date(2026, 8, 1))
    assert info.excluded_periods == []
    assert info.comparison_excluded_partial_period is False


def test_trailing_week_within_today_is_partial():
    # 2026-07-13 is a Monday; the week bucket runs 2026-07-13..2026-07-19.
    info = detect_partial_periods(["2026-07-06", "2026-07-13"], "week", date(2026, 7, 15))
    assert info.excluded_periods == ["2026-07-13"]


def test_empty_period_list_returns_default():
    info = detect_partial_periods([], "month", date(2026, 7, 15))
    assert info.excluded_periods == []
    assert info.partial_periods == []


# ── compute_trend_metrics ───────────────────────────────────────────────────


def test_consistent_upward_trend():
    tm = compute_trend_metrics(
        ["2026-01-01", "2026-02-01", "2026-03-01"], [10, 20, 30], "month", date(2026, 8, 1)
    )
    assert tm.trend_consistency == "consistent_upward"
    assert tm.endpoint_direction == "upward"
    assert tm.slope_direction == "upward"
    assert tm.comparable_period_count == 3


def test_consistent_downward_trend():
    tm = compute_trend_metrics(
        ["2026-01-01", "2026-02-01", "2026-03-01"], [30, 20, 10], "month", date(2026, 8, 1)
    )
    assert tm.trend_consistency == "consistent_downward"
    assert tm.endpoint_direction == "downward"
    assert tm.slope_direction == "downward"


def test_flat_trend():
    # AI-INTELLIGENCE-018: "flat" now requires every adjacent change to be
    # exactly zero (monotonicity-based) — a genuinely stationary series.
    tm = compute_trend_metrics(
        ["2026-01-01", "2026-02-01", "2026-03-01"], [100, 100, 100], "month", date(2026, 8, 1)
    )
    assert tm.trend_consistency == "flat"
    assert tm.monotonicity == "flat"


def test_small_real_fluctuation_is_not_flat():
    # [100, 101, 100] has real (if small) up-then-down movement — under the
    # stricter monotonicity-based definition this is fluctuation, not "flat"
    # (which previously only meant "within the 5% endpoint/slope threshold").
    tm = compute_trend_metrics(
        ["2026-01-01", "2026-02-01", "2026-03-01"], [100, 101, 100], "month", date(2026, 8, 1)
    )
    assert tm.trend_consistency == "mixed_or_fluctuating"
    assert tm.monotonicity == "non_monotonic"


def test_mixed_signal_trend():
    # A mid-series spike followed by a drop back below the start: slope over
    # the whole series trends upward on average, but the endpoint (first vs
    # last) shows a decline — this is the exact contradiction the old
    # independent growth_rate/trend_direction calculators used to produce.
    tm = compute_trend_metrics(
        ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"],
        [50, 90, 95, 40],
        "month",
        date(2026, 8, 1),
    )
    assert tm.trend_consistency == "mixed_or_fluctuating"
    assert tm.endpoint_direction == "downward"
    assert tm.monotonicity == "non_monotonic"


def test_incomplete_trailing_month_excluded_from_trend():
    tm = compute_trend_metrics(
        ["2026-05-01", "2026-06-01", "2026-07-01"], [10, 20, 5], "month", date(2026, 7, 10)
    )
    assert tm.comparison_excluded_partial_period is True
    assert tm.excluded_periods == ["2026-07-01"]
    assert tm.comparable_period_count == 2
    assert tm.last_comparable_period == "2026-06-01"
    # Endpoint direction reflects only the two complete months (10 -> 20 =
    # upward), never the partial trailing bucket's lower value.
    assert tm.endpoint_direction == "upward"


def test_insufficient_comparable_periods():
    tm = compute_trend_metrics(["2026-07-01"], [10], "month", date(2026, 7, 10))
    assert tm.trend_consistency == "insufficient_data"
    assert tm.endpoint_change is None
    assert tm.slope is None
    assert tm.comparable_period_count == 0


def test_insufficient_when_only_one_complete_period_remains():
    # Two months returned, but the trailing one is still in progress -> only
    # one comparable period remains, which is not enough for a trend verdict.
    tm = compute_trend_metrics(
        ["2026-06-01", "2026-07-01"], [10, 5], "month", date(2026, 7, 10)
    )
    assert tm.trend_consistency == "insufficient_data"
    assert tm.comparable_period_count == 1


def test_zero_baseline_percentage_handling():
    tm = compute_trend_metrics(
        ["2026-01-01", "2026-02-01"], [0, 10], "month", date(2026, 8, 1)
    )
    assert tm.endpoint_change == 10
    assert tm.endpoint_percentage_change is None  # division by zero avoided
    assert tm.endpoint_direction == "upward"


def test_slope_threshold_flat_vs_moving():
    flat = compute_trend_metrics(
        ["2026-01-01", "2026-02-01", "2026-03-01"], [1000, 1005, 998], "month", date(2026, 8, 1)
    )
    moving = compute_trend_metrics(
        ["2026-01-01", "2026-02-01", "2026-03-01"], [1000, 1200, 1400], "month", date(2026, 8, 1)
    )
    assert flat.slope_direction == "flat"
    assert moving.slope_direction == "upward"
