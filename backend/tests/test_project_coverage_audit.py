"""Regression coverage for the general project coverage audit.

These cases exercise question *families*, not one-off SQL strings: synonymous
cohort wording, compositional dimensions, catalog-backed data quality metrics,
scalar-vs-series semantics and deterministic multi-KPI comparisons.
"""

import pytest

from app.database_intelligence.models import ViewMetadata
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.services.deterministic_sql_builder import DeterministicSQL, DeterministicSQLBuilder
from app.services.query_analyzer import QueryAnalyzer
from app.sql_validator.validator import SQLValidator

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


def _plan(question: str) -> QueryPlan:
    return QueryPlanner().build_plan(
        question,
        QueryAnalyzer().analyze(question),
        tables=[],
        views=[VIEW],
    )


@pytest.mark.parametrize(
    "question",
    [
        "Randevuyu gec alan hastalar gercekten geliyor mu?",
        "24 saat kala alinan randevularin durumu nedir?",
        "Acele randevu alanlarda no show var mi?",
        "Gec alinan randevular bolumlerde nasil sonuc vermis?",
    ],
)
def test_last_minute_language_family_resolves_to_verified_cohort(question: str):
    plan = _plan(question)

    assert plan.analysis_type == "cohort_analysis"
    assert plan.cohort and "lead_time_under_24h" in plan.cohort
    assert {"appointment_count", "completed_appointment_rate", "no_show_rate"} <= set(
        plan.metrics
    )


def test_cohort_preserves_requested_department_breakdown():
    plan = _plan("Gec alinan randevular bolumlerde nasil sonuc vermis?")
    built = DeterministicSQLBuilder().build(plan)

    assert isinstance(built, DeterministicSQL)
    assert built.result_schema == "CohortResult"
    assert "GenelRandevuBolumAdi" in built.expected_aliases
    assert ".nodes('/i')" in built.sql
    assert "GROUP BY dept_atomic.value" in built.sql
    assert SQLValidator().validate(built.sql).valid


@pytest.mark.parametrize(
    "question,metric",
    [
        ("Tarih araligi bozuk kayitlari say.", "invalid_date_range_count"),
        ("Randevu suresi tarih farkiyla tutmuyor mu?", "duration_mismatch_count"),
    ],
)
def test_data_quality_language_family_uses_verified_metric(question: str, metric: str):
    plan = _plan(question)

    assert plan.analysis_type == "data_quality"
    assert plan.metrics[0] == metric


def test_grouped_data_quality_uses_distribution_contract():
    plan = _plan("Sube bazinda eksik doktor kaydi dagilimi")
    built = DeterministicSQLBuilder().build(plan)

    assert isinstance(built, DeterministicSQL)
    assert built.result_schema == "DistributionResult"
    assert built.expected_aliases[:2] == ["SubeAdi", "missing_doctor_count"]


def test_source_and_status_breakdown_keeps_both_dimensions():
    plan = _plan("Kaynak ve durum kiriliminda randevular nasil?")
    built = DeterministicSQLBuilder().build(plan)

    assert plan.analysis_type == "cross_analysis"
    assert set(plan.dimensions) == {"GenelRandevuKaynakAdi", "RandevuDurumu"}
    assert isinstance(built, DeterministicSQL)
    assert built.result_schema == "DistributionResult"


def test_daily_average_is_scalar_unless_trend_is_explicit():
    scalar = _plan("2024 yilinda gunluk ortalama randevu sayisi nedir")
    trend = _plan("2024 yilinda gunluk ortalama randevu sayisi trendi nedir")

    assert scalar.analysis_type == "average"
    assert scalar.grouping_granularity is None
    assert trend.analysis_type == "time_trend"
    assert trend.grouping_granularity == "day"


def test_yogunluk_does_not_accidentally_mean_daily_granularity():
    plan = _plan("Hastanede bugun trafik nasil, randevu var mi yogunluk?")

    assert plan.analysis_type == "count"
    assert plan.metrics == ["appointment_count"]
    assert plan.dimensions == []
    assert plan.grouping_granularity is None


def test_explicit_two_period_difference_wins_over_generic_variance_wording():
    plan = _plan("Bolumlerde bu ay gecen aya gore fark var mi?")
    built = DeterministicSQLBuilder().build(plan)

    assert plan.analysis_type == "period_comparison"
    assert isinstance(built, DeterministicSQL)
    assert {"current_period_count", "baseline_period_count", "absolute_change"} <= set(
        built.expected_aliases
    )


def test_multi_kpi_performance_uses_deterministic_period_comparison():
    plan = _plan("Son zamanlarda durumumuz nasil?")
    built = DeterministicSQLBuilder().build(plan)

    assert plan.analysis_type == "multi_metric_performance"
    assert isinstance(built, DeterministicSQL)
    assert built.result_schema == "PeriodComparisonResult"
    assert {
        "current_period_count",
        "current_completed_appointment_rate",
        "current_no_show_rate",
        "current_unique_patient_count",
    } <= set(built.expected_aliases)
    assert SQLValidator().validate(built.sql).valid


def test_salary_is_a_controlled_limitation_not_an_invented_metric():
    plan = _plan("Doktor maaslarini subelere gore karsilastir")

    assert plan.answerable is False
    assert "maaş" in (plan.answerability_reason or "").lower()
    assert "Randevu hacmi" in (plan.answerability_reason or "")
