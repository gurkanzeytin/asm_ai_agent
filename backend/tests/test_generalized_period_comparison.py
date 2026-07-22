from __future__ import annotations

# ruff: noqa: E501
from datetime import date

import pytest

from app.analytics.result_contracts import PeriodComparisonResult
from app.database_intelligence.models import ViewMetadata
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import PeriodPlan
from app.planning.planner import QueryPlanner
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.services.query_analyzer import QueryAnalyzer

TODAY = date(2026, 7, 17)
VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


def _pipeline(question: str):
    analysis = QueryAnalyzer(today=TODAY).analyze(question)
    plan = QueryPlanner().build_plan(question, analysis, [], views=[VIEW])
    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    return analysis, plan, built


@pytest.mark.parametrize(
    "question,expected",
    [
        (
            "2023 Eylul ile 2023 Ekim randevu sayilarini karsilastir.",
            (("Eylül 2023", "2023-09-01", "2023-10-01"), ("Ekim 2023", "2023-10-01", "2023-11-01")),
        ),
        (
            "2022 Aralik ile 2023 Mart randevu sayilarini karsilastir.",
            (("Aralık 2022", "2022-12-01", "2023-01-01"), ("Mart 2023", "2023-03-01", "2023-04-01")),
        ),
        (
            "2024 Subat ile 2024 Mart randevu sayilarini karsilastir.",
            (("Şubat 2024", "2024-02-01", "2024-03-01"), ("Mart 2024", "2024-03-01", "2024-04-01")),
        ),
        (
            "2023 Subat ile 2024 Subat randevu sayilarini karsilastir.",
            (("Şubat 2023", "2023-02-01", "2023-03-01"), ("Şubat 2024", "2024-02-01", "2024-03-01")),
        ),
        (
            "2021 Ocak ile 2025 Aralik randevu sayilarini karsilastir.",
            (("Ocak 2021", "2021-01-01", "2021-02-01"), ("Aralık 2025", "2025-12-01", "2026-01-01")),
        ),
        (
            "2022 ile 2023 randevu sayilarini karsilastir.",
            (("2022", "2022-01-01", "2023-01-01"), ("2023", "2023-01-01", "2024-01-01")),
        ),
        (
            "Bu ay ile gecen ay randevu sayilarini karsilastir.",
            (("bu ay", "2026-07-01", "2026-08-01"), ("gecen ay", "2026-06-01", "2026-07-01")),
        ),
        (
            "Son 30 gun ile onceki 30 gun randevu sayilarini karsilastir.",
            (("son 30 gun", "2026-06-18", "2026-07-18"), ("onceki 30 gun", "2026-05-19", "2026-06-18")),
        ),
        (
            "1 Ocak 2023-15 Ocak 2023 ile 1 Mart 2023-15 Mart 2023 randevu sayilarini karsilastir.",
            (("1 ocak 2023-15 ocak 2023", "2023-01-01", "2023-01-16"), ("1 mart 2023-15 mart 2023", "2023-03-01", "2023-03-16")),
        ),
        (
            "2025 Aralik ile 2021 Ocak randevu sayilarini karsilastir.",
            (("Aralık 2025", "2025-12-01", "2026-01-01"), ("Ocak 2021", "2021-01-01", "2021-02-01")),
        ),
    ],
)
def test_period_comparison_pipeline_is_general_and_ordered(question, expected):
    analysis, plan, built = _pipeline(question)

    assert len(analysis.detected_dates) == 2
    assert plan.analysis_type == "period_comparison"
    assert [
        (period.label, period.start_inclusive, period.end_exclusive)
        for period in plan.periods
    ] == list(expected)

    baseline, current = plan.periods
    for period in (baseline, current):
        assert f"BaslangicTarihi >= '{period.start_inclusive}'" in built.sql
        assert f"BaslangicTarihi < '{period.end_exclusive}'" in built.sql
    assert built.sql.count("AS current_period_count") == 1
    assert built.sql.count("AS baseline_period_count") == 1
    assert "NULLIF" in built.sql

    compliance = PlanComplianceValidator().check(
        built.sql,
        plan,
        expected_aliases=built.expected_aliases,
        deterministic=True,
    )
    assert compliance.compliant, compliance.missing

    row = PeriodComparisonResult(
        current_period_label=current.label,
        baseline_period_label=baseline.label,
        current_period_count=125,
        baseline_period_count=100,
        absolute_change=25,
        percentage_change=25.0,
    )
    assert row.is_complete()
    assert row.absolute_change > 0
    assert row.percentage_change == 100 * row.absolute_change / row.baseline_period_count


def _month_pairs():
    values = []
    for index in range(50):
        first_year = 2000 + (index * 7) % 31
        second_year = 2000 + (index * 11 + 3) % 31
        first_month = index % 12 + 1
        second_month = (index * 5 + 8) % 12 + 1
        values.append((first_year, first_month, second_year, second_month))
    return values


@pytest.mark.parametrize("first_year,first_month,second_year,second_month", _month_pairs())
def test_generated_month_pairs_use_next_month_as_exclusive_boundary(
    first_year, first_month, second_year, second_month
):
    names = (
        "", "Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran",
        "Temmuz", "Agustos", "Eylul", "Ekim", "Kasim", "Aralik",
    )
    question = (
        f"{first_year} {names[first_month]} ile {second_year} {names[second_month]} "
        "randevu sayilarini karsilastir."
    )
    _, plan, built = _pipeline(question)

    expected = []
    for year, month in ((first_year, first_month), (second_year, second_month)):
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        expected.append((date(year, month, 1).isoformat(), date(next_year, next_month, 1).isoformat()))
    assert [(p.start_inclusive, p.end_exclusive) for p in plan.periods] == expected
    assert PlanComplianceValidator().check(built.sql, plan).compliant


def test_compliance_accepts_count_case_equivalent():
    _, plan, _ = _pipeline("2022 Aralik ile 2023 Mart randevu sayilarini karsilastir.")
    baseline, current = plan.periods
    sql = f"""
        SELECT
          COUNT(CASE WHEN BaslangicTarihi >= '{current.start_inclusive}' AND BaslangicTarihi < '{current.end_exclusive}' THEN 1 END) AS current_period_count,
          COUNT(CASE WHEN BaslangicTarihi >= '{baseline.start_inclusive}' AND BaslangicTarihi < '{baseline.end_exclusive}' THEN 1 END) AS baseline_period_count
        FROM dbo.vw_RandevuRaporu
        WHERE (BaslangicTarihi >= '{current.start_inclusive}' AND BaslangicTarihi < '{current.end_exclusive}')
           OR (BaslangicTarihi >= '{baseline.start_inclusive}' AND BaslangicTarihi < '{baseline.end_exclusive}');
    """
    assert PlanComplianceValidator().check(sql, plan).compliant


@pytest.mark.parametrize(
    "bad_sql",
    [
        "SELECT COUNT(*) AS current_period_count FROM dbo.vw_RandevuRaporu WHERE BaslangicTarihi >= '2022-12-01' AND BaslangicTarihi < '2023-04-01';",
        "SELECT SUM(CASE WHEN BaslangicTarihi >= '2022-12-01' AND BaslangicTarihi < '2023-04-01' THEN 1 ELSE 0 END) AS current_period_count, SUM(CASE WHEN BaslangicTarihi >= '2022-12-01' AND BaslangicTarihi < '2023-04-01' THEN 1 ELSE 0 END) AS baseline_period_count FROM dbo.vw_RandevuRaporu WHERE (BaslangicTarihi >= '2022-12-01') OR (BaslangicTarihi < '2023-04-01');",
    ],
)
def test_compliance_rejects_single_or_merged_period_count(bad_sql):
    _, plan, _ = _pipeline("2022 Aralik ile 2023 Mart randevu sayilarini karsilastir.")
    assert not PlanComplianceValidator().check(bad_sql, plan).compliant


def test_compliance_rejects_date_literal_outside_query_plan():
    _, plan, built = _pipeline("2022 Aralik ile 2023 Mart randevu sayilarini karsilastir.")
    poisoned_sql = built.sql.replace("2023-03-01", "2030-03-01", 1)
    result = PlanComplianceValidator().check(poisoned_sql, plan)
    assert not result.compliant
    assert any("outside QueryPlan" in issue for issue in result.missing)


def test_compliance_requires_exactly_two_plan_periods():
    _, plan, built = _pipeline("2022 Aralik ile 2023 Mart randevu sayilarini karsilastir.")
    invalid = plan.model_copy(
        update={
            "periods": [
                PeriodPlan(
                    label="only",
                    start_inclusive="2022-12-01",
                    end_exclusive="2023-01-01",
                    column="BaslangicTarihi",
                )
            ]
        }
    )
    result = PlanComplianceValidator().check(built.sql, invalid)
    assert not result.compliant
    assert "period comparison requires exactly two plan periods" in result.missing


def test_zero_baseline_percentage_is_null_safe_and_contract_complete():
    _, _, built = _pipeline("2022 ile 2023 randevu sayilarini karsilastir.")
    assert "/ NULLIF((" in built.sql
    result = PeriodComparisonResult(
        baseline_period_count=0,
        current_period_count=5,
        absolute_change=5,
        percentage_change=None,
    )
    assert result.is_complete()
    assert result.percentage_change is None
