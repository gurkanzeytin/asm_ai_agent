"""Tests for ResultValidator.check_shape (Phase 6): the post-execution,
pre-analytics gate comparing an executed result's columns against the
deterministic SQL's expected alias contract.
"""

from datetime import UTC, datetime

from app.analytics.result_validation import ResultValidator
from app.application_models.workflow_models import QueryResult
from app.planning.models import QueryPlan


def _result(columns, rows) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


def _plan(**overrides) -> QueryPlan:
    return QueryPlan(question="q", **overrides)


def test_no_expected_aliases_is_trivially_valid():
    verdict = ResultValidator().check_shape(_result(["x"], [{"x": 1}]), None, [])
    assert verdict.valid is True


def test_missing_expected_metric_column_is_invalid():
    plan = _plan(
        dimensions=["SubeAdi"], metrics=["appointment_count", "completed_appointment_rate"]
    )
    result = _result(
        ["SubeAdi", "appointment_count"], [{"SubeAdi": "Merkez", "appointment_count": 10}]
    )
    verdict = ResultValidator().check_shape(
        result, plan, ["SubeAdi", "appointment_count", "completed_appointment_rate"]
    )
    assert verdict.valid is False
    assert "completed_appointment_rate" in verdict.missing_columns


def test_legitimate_all_zero_grouped_result_is_valid():
    plan = _plan(
        dimensions=["SubeAdi"], metrics=["appointment_count", "completed_appointment_rate"]
    )
    result = _result(
        ["SubeAdi", "appointment_count", "completed_appointment_rate"],
        [{"SubeAdi": "Merkez", "appointment_count": 0, "completed_appointment_rate": 0.0}],
    )
    verdict = ResultValidator().check_shape(
        result, plan, ["SubeAdi", "appointment_count", "completed_appointment_rate"]
    )
    assert verdict.valid is True
    assert verdict.actual_shape == "grouped"


def test_unexpected_extra_column_on_deterministic_path_is_invalid():
    plan = _plan(dimensions=["SubeAdi"], metrics=["appointment_count"])
    result = _result(
        ["SubeAdi", "appointment_count", "mystery_column"],
        [{"SubeAdi": "Merkez", "appointment_count": 5, "mystery_column": 1}],
    )
    verdict = ResultValidator().check_shape(result, plan, ["SubeAdi", "appointment_count"])
    assert verdict.valid is False
    assert "mystery_column" in verdict.unexpected_columns


def test_empty_result_with_matching_columns_is_valid():
    plan = _plan(dimensions=["SubeAdi"], metrics=["appointment_count"])
    result = _result(["SubeAdi", "appointment_count"], [])
    verdict = ResultValidator().check_shape(result, plan, ["SubeAdi", "appointment_count"])
    assert verdict.valid is True


_GROUPED_METRICS = [
    "appointment_count",
    "completed_appointment_rate",
    "appointment_duration_average",
]
_GROUPED_ALIASES = ["SubeAdi", *_GROUPED_METRICS]


def _grouped_row(branch: str, count: int, rate: float, duration: float) -> dict:
    return {
        "SubeAdi": branch,
        "appointment_count": count,
        "completed_appointment_rate": rate,
        "appointment_duration_average": duration,
    }


def test_multiple_grouped_rows_pass():
    plan = _plan(dimensions=["SubeAdi"], metrics=_GROUPED_METRICS)
    result = _result(
        _GROUPED_ALIASES,
        [
            _grouped_row("Merkez", 89, 76.5, 22.0),
            _grouped_row("Kadikoy", 54, 68.0, 27.5),
        ],
    )
    verdict = ResultValidator().check_shape(result, plan, _GROUPED_ALIASES)
    assert verdict.valid is True
    assert verdict.expected_shape == "grouped"
    assert verdict.actual_shape == "grouped"


def test_one_grouped_row_with_dimension_and_all_metrics_passes():
    plan = _plan(dimensions=["SubeAdi"], metrics=_GROUPED_METRICS)
    result = _result(_GROUPED_ALIASES, [_grouped_row("Merkez", 89, 76.5, 22.0)])
    verdict = ResultValidator().check_shape(result, plan, _GROUPED_ALIASES)
    assert verdict.valid is True


def test_scalar_row_fails_grouped_plan():
    plan = _plan(dimensions=["SubeAdi"], metrics=["appointment_count"])
    # Deterministic builder expected a dimension column that never appears —
    # a bare scalar total returned instead of the planned grouped shape.
    result = _result(["appointment_count"], [{"appointment_count": 89}])
    verdict = ResultValidator().check_shape(result, plan, ["SubeAdi", "appointment_count"])
    assert verdict.valid is False
    assert "SubeAdi" in verdict.missing_columns
