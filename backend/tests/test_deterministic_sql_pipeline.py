# ruff: noqa: E501

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.analytics.result_contracts import TypedResultNormalizer
from app.analytics.result_reasoning import ResultReasoner
from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import ViewMetadata
from app.llm.schemas import LLMResponse
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import DateFilterPlan, PeriodPlan, QueryPlan
from app.planning.planner import QueryPlanner
from app.semantics import catalog
from app.semantics.models import SemanticFrame
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
    UnsupportedPlan,
)
from app.services.query_analyzer import QueryAnalyzer
from app.services.sql_service import SQLService
from app.sql_validator.validator import SQLValidator

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


class _Parser:
    def parse_sql(self, content: str) -> str:
        return content


class _Provider:
    calls = 0

    async def generate(self, *args, **kwargs):
        self.calls += 1
        return LLMResponse(
            content="SELECT COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu;",
            model="fake",
            latency_ms=1.0,
        )

    def get_metadata(self):
        return {"provider": "fake"}


def _result(columns, rows):
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


def _plan(question: str) -> QueryPlan:
    return QueryPlanner().build_plan(
        question,
        QueryAnalyzer().analyze(question),
        tables=[],
        views=[VIEW],
    )


@pytest.mark.asyncio
async def test_deterministic_builder_selection_skips_llm():
    provider = _Provider()
    service = SQLService(provider, _Parser(), SQLValidator())
    generated = await service.generate_sql(
        "prompt", query_plan=_plan("Subelere gore gelmeme oranlari nedir?")
    )
    assert generated.sql_source == "deterministic"
    assert provider.calls == 0
    assert "NULLIF" in generated.sql


@pytest.mark.asyncio
async def test_llm_fallback_selection_for_unsupported_plan():
    provider = _Provider()
    service = SQLService(provider, _Parser(), SQLValidator())
    generated = await service.generate_sql(
        "prompt",
        query_plan=QueryPlan(question="q", analysis_type="unsupported_complex"),
    )
    assert generated.sql_source == "llm"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_typed_schema_reasoning_plan_uses_llm_sql_with_plan_compliance():
    class DurationProvider(_Provider):
        async def generate(self, *args, **kwargs):
            self.calls += 1
            return LLMResponse(
                content=(
                    "SELECT AVG(CAST(RandevuSuresi AS FLOAT)) "
                    "AS appointment_duration_average "
                    "FROM dbo.vw_RandevuRaporu "
                    "WHERE BaslangicTarihi >= '2025-01-01' "
                    "AND BaslangicTarihi < DATEADD(day, 1, '2025-12-31');"
                ),
                model="fake",
                latency_ms=1.0,
            )

    provider = DurationProvider()
    service = SQLService(provider, _Parser(), SQLValidator())
    plan = QueryPlan(
        question="Geçen seneki görüşmeler ne kadar vakit almış?",
        planning_source="llm_schema_reasoning",
        output_table="dbo.vw_RandevuRaporu",
        fact_table="dbo.vw_RandevuRaporu",
        date_filters=[
            DateFilterPlan(
                expression="schema_reasoning:previous_year",
                start_date="2025-01-01",
                end_date="2025-12-31",
                column="BaslangicTarihi",
            )
        ],
        analysis_type="average",
        aggregation="AVG(CAST(RandevuSuresi AS FLOAT))",
        metrics=["appointment_duration_average"],
        required_columns=["RandevuSuresi", "BaslangicTarihi"],
    )

    generated = await service.generate_sql("prompt", query_plan=plan)

    assert generated.sql_source == "llm"
    assert provider.calls == 1


def test_metric_sql_mapping_excludes_unverified_metrics():
    mapping = DeterministicSQLBuilder().metric_sql_map()
    assert mapping["appointment_count"] == "COUNT(*)"
    assert "patient_id_mismatch_count" not in mapping
    for metric in catalog.load_metric_catalog().metrics:
        if metric.status == "requires_verified_mapping":
            assert metric.id not in mapping


def test_cohort_sql_generation_and_contract():
    built = DeterministicSQLBuilder().build(
        _plan("Randevusunu son dakika alanlarin gelme durumu nasil?")
    )
    assert not isinstance(built, UnsupportedPlan)
    assert built.result_schema == "CohortResult"
    assert "DATEDIFF(hour, CreatedDate, BaslangicTarihi) BETWEEN 0 AND 24" in built.sql
    assert "cohort_total_count" in built.expected_aliases
    assert "HastaAdi" not in built.sql


def test_period_pair_sql_generation():
    built = DeterministicSQLBuilder().build(
        _plan("Bu ay ile gecen ayin randevu sayilarini karsilastir.")
    )
    assert not isinstance(built, UnsupportedPlan)
    assert built.result_schema == "PeriodComparisonResult"
    assert "current_period_count" in built.sql
    assert "baseline_period_count" in built.sql
    assert "absolute_change" in built.sql
    assert "percentage_change" in built.sql
    assert " OR " in built.sql


def test_anomaly_sql_generation_without_having():
    built = DeterministicSQLBuilder().build(_plan("Bu aralar hangi subede gelmeme orani artmis?"))
    assert not isinstance(built, UnsupportedPlan)
    assert built.result_schema == "AnomalyResult"
    assert "SubeAdi" in built.sql
    assert "current_no_show_rate" in built.sql
    assert "baseline_no_show_rate" in built.sql
    assert "İptal" not in built.sql
    assert "cancelled" not in built.sql
    assert "HAVING" not in built.sql.upper()


def test_generic_negation_hint_routes_to_llm_not_literal_sql():
    """A generic negation ("uyruğu Türkiye olmayan") is carried as an
    unstructured "NEGATION: ..." planner hint for the LLM. The deterministic
    builder must NOT render that hint verbatim into the WHERE clause (which
    produced a SQL syntax error live 2026-07-28) — it hands the plan to the
    LLM instead."""
    built = DeterministicSQLBuilder().build(
        _plan("2024 yilinda uyrugu Turkiye olmayan hastalarin randevu sayisi")
    )
    assert isinstance(built, UnsupportedPlan)
    assert "negation" in built.reason.lower()


def test_top_percentile_renders_top_n_percent():
    """ "en üstteki %10'u göster" is a TOP (N) PERCENT slice, not TOP N rows and
    not an unfiltered dump of every group (live 2026-07-28: returned all
    doctors, the %10 was ignored/mis-read as a row limit)."""
    plan = _plan("2024 yilinda doktorlar arasinda randevu sayisi en ustteki %10 u goster")
    assert plan.percentile == 10
    assert plan.limit is None
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "TOP (10) PERCENT" in built.sql
    assert "ORDER BY" in built.sql.upper()


def test_bottom_percentile_orders_ascending():
    plan = _plan("2024 yilinda en alttaki %10 doktoru goster")
    assert plan.percentile == 10
    built = DeterministicSQLBuilder().build(plan)
    assert "TOP (10) PERCENT" in built.sql
    assert "ASC" in built.sql.upper()


def test_ratio_percent_is_not_a_percentile_slice():
    """A ratio value ("gelmeme oranı %10") must not become a TOP (N) PERCENT."""
    plan = _plan("2024 yilinda gelmeme orani %10 olan bolumler")
    assert plan.percentile is None


def test_variance_sql_generation_uses_cte_summary():
    built = DeterministicSQLBuilder().build(_plan("Doktorlar arasinda cok fark var mi?"))
    assert not isinstance(built, UnsupportedPlan)
    assert built.result_schema == "VarianceResult"
    assert "WITH group_counts" in built.sql
    assert "average_appointments" in built.sql
    assert "SELECT TOP" not in built.sql.upper()


def test_result_alias_contract_and_normalization():
    result = _result(
        ["cohort_total_count", "completed_rate", "cancelled_rate", "no_show_rate"],
        [
            {
                "cohort_total_count": Decimal("10"),
                "completed_rate": Decimal("80.5"),
                "cancelled_rate": None,
                "no_show_rate": Decimal("5"),
            }
        ],
    )
    normalized = TypedResultNormalizer().normalize(
        result,
        schema_name="CohortResult",
        expected_aliases=["cohort_total_count", "completed_rate", "cancelled_rate", "no_show_rate"],
    )
    assert normalized.rows[0]["cohort_total_count"] == 10
    assert normalized.rows[0]["completed_rate"] == 80.5
    assert normalized.rows[0]["cancelled_rate"] is None


def test_typed_result_validation_warning_on_missing_alias():
    normalized = TypedResultNormalizer().normalize(
        _result(["cohort_total_count"], [{"cohort_total_count": 1}]),
        schema_name="CohortResult",
    )
    assert normalized.warnings


def test_result_reasoning_uses_typed_contract():
    result = _result(
        [
            "group_count",
            "total_appointments",
            "average_appointments",
            "minimum_appointments",
            "maximum_appointments",
            "max_to_average_ratio",
            "top_10_percent_share",
        ],
        [
            {
                "group_count": 5,
                "total_appointments": 100,
                "average_appointments": 20,
                "minimum_appointments": 5,
                "maximum_appointments": 50,
                "max_to_average_ratio": 2.5,
                "top_10_percent_share": 40,
            }
        ],
    )
    outcome = ResultReasoner().reason(
        result, QueryPlan(question="q"), result_schema="VarianceResult"
    )
    assert any("ortalama" in finding for finding in outcome.findings)


def test_adaptive_retry_updates_deterministic_windows():
    built = DeterministicSQLBuilder().build(
        _plan("Randevusunu son dakika alanlarin gelme durumu nasil?"), adaptive_retry=True
    )
    assert not isinstance(built, UnsupportedPlan)
    assert "BETWEEN 0 AND 48" in built.sql
    period = DeterministicSQLBuilder().build(
        _plan("Bu aralar hangi subede gelmeme orani artmis?"), adaptive_retry=True
    )
    assert not isinstance(period, UnsupportedPlan)
    assert "DATEADD(day, -90" in period.sql
    assert "DATEADD(day, -180" in period.sql


def test_deterministic_sql_compliance_and_raw_detail_prevention():
    plan = _plan("Subelere gore gelmeme oranlari nedir?")
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    result = PlanComplianceValidator().check(
        built.sql,
        plan,
        expected_aliases=built.expected_aliases,
        deterministic=True,
    )
    assert result.compliant, result.missing
    bad = "SELECT HastaAdi, COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu;"
    assert any(
        "raw detail" in missing
        for missing in PlanComplianceValidator().check(bad, plan, deterministic=True).missing
    )


@pytest.mark.parametrize(
    "question,schema,contains",
    [
        (
            "Randevusunu son dakika alanlarin gelme durumu nasil?",
            "CohortResult",
            "cohort_total_count",
        ),
        ("Bu aralar hangi subede gelmeme orani artmis?", "AnomalyResult", "rate_point_change"),
        ("Doktorlar arasinda cok fark var mi?", "VarianceResult", "top_10_percent_share"),
        (
            "Bu ay ile gecen ayin randevu sayilarini karsilastir.",
            "PeriodComparisonResult",
            "percentage_change",
        ),
        ("Subelere gore gelmeme oranlari nedir?", "RatioResult", "no_show_rate"),
    ],
)
def test_five_acceptance_questions(question, schema, contains):
    plan = _plan(question)
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert built.result_schema == schema
    assert contains in built.sql
    assert "HastaAdi" not in built.sql
    assert "HastaGSM" not in built.sql


# ═══════════════════════ Multi-metric deterministic SQL ══════════════════════


def test_standard_builder_emits_one_column_per_metric_with_distinct_aliases():
    plan = _plan(
        "Subelere gore randevu sayisi, gerceklesme orani ve ortalama randevu suresini karsilastir"
    )
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "appointment_count" in built.metric_aliases
    assert "completed_appointment_rate" in built.metric_aliases
    assert "appointment_duration_average" in built.metric_aliases
    assert len(set(built.metric_aliases.values())) == len(built.metric_aliases)
    assert "GROUP BY SubeAdi" in built.sql
    assert "NULLIF" in built.sql
    for alias in built.metric_aliases.values():
        assert f"AS {alias}" in built.sql


def test_scalar_appointment_and_unique_patient_metrics_do_not_group_by_patient_id():
    plan = _plan("2025 randevu sayisi ile tekil hasta sayisini birlikte goster")

    assert plan.metrics == ["appointment_count", "unique_patient_count"]
    assert plan.dimensions == []
    assert plan.projection == []

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "COUNT(*) AS appointment_count" in built.sql
    assert "COUNT(DISTINCT HastaId) AS unique_patient_count" in built.sql
    assert "HastaId AS HastaId" not in built.sql
    assert "GROUP BY" not in built.sql.upper()

    result = PlanComplianceValidator().check(
        built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
    )
    assert result.compliant is True


def test_appointments_per_patient_repeat_behavior_builds_deterministic_sql():
    plan = _plan("2025 hasta basina ortalama randevu adedi nedir")

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["appointments_per_patient"]

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert (
        "CAST(COUNT(*) AS FLOAT) / NULLIF(COUNT(DISTINCT HastaId), 0) AS appointments_per_patient"
        in built.sql
    )
    assert "BaslangicTarihi >= '2025-01-01'" in built.sql


def test_year_scoped_average_appointment_duration_builds_deterministic_sql():
    plan = _plan("2024 yılının ortalama randevu süresi nedir?")

    assert plan.metrics == ["appointment_duration_average"]
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "AVG(CAST(RandevuSuresi AS FLOAT))" in built.sql
    assert "BaslangicTarihi >= '2024-01-01'" in built.sql
    assert "2024-12-31" in built.sql
    assert SQLValidator().validate(built.sql).valid


def test_repeat_patient_count_uses_having_cte_without_patient_group_leak():
    plan = _plan("2024 yilinda birden fazla randevusu olan kac hasta var?")

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["repeat_patient_count"]
    assert plan.dimensions == []

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "WITH patient_repeats AS" in built.sql
    assert "GROUP BY HastaId" in built.sql
    assert "HAVING COUNT(*) > 1" in built.sql
    assert "SELECT COUNT(*) AS repeat_patient_count" in built.sql
    assert "HastaId AS HastaId" not in built.sql


def test_repeat_patient_count_clears_stale_semantic_ranking_and_aggregation():
    question = "2024 yilinda birden fazla randevusu olan kac hasta var?"
    semantic_frame = SemanticFrame(
        question=question,
        goal="RANK",
        primary_subject="Patient",
        fact_subject="Appointment",
        requested_output="ranking",
        question_type="ranking",
    )
    plan = QueryPlanner().build_plan(
        question,
        QueryAnalyzer().analyze(question),
        tables=[],
        semantic_frame=semantic_frame,
        views=[VIEW],
    )

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["repeat_patient_count"]
    assert plan.aggregation is None
    assert plan.ranking is None

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    compliance = PlanComplianceValidator().check(
        built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


def test_cross_branch_repeat_patient_routes_to_relationship_cte():
    plan = _plan("2024 yilinda hangi hastalar farkli subelerde tekrar tekrar islem gormus?")

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["cross_branch_repeat_patient_count"]
    assert plan.dimensions == []

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "WITH cross_branch_patients AS" in built.sql
    assert "COUNT(DISTINCT SubeAdi) > 1" in built.sql
    assert "SELECT COUNT(*) AS cross_branch_repeat_patient_count" in built.sql


def test_cross_branch_repeat_breakdown_cte_passes_projection_compliance():
    plan = _plan(
        "2024 yilinda hangi hastalar farkli subelerde tekrar tekrar islem gormus hizmetlere gore dagit"
    )

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["cross_branch_repeat_patient_count"]
    assert plan.dimensions == ["HizmetAdi"]
    assert plan.projection == []

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "SELECT v.HizmetAdi AS HizmetAdi" in built.sql
    assert "GROUP BY v.HizmetAdi" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True


def test_cross_branch_repeat_keeps_explicit_branch_name_breakdown():
    plan = _plan("Şube adı bazında farklı şubelerde tekrar eden hasta sayısını göster.")

    assert plan.metrics == ["cross_branch_repeat_patient_count"]
    assert plan.dimensions == ["SubeAdi"]
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "v.SubeAdi AS SubeAdi" in built.sql
    assert "GROUP BY v.SubeAdi" in built.sql


def test_same_day_multi_service_patient_is_scalar_until_breakdown_is_explicit():
    plan = _plan("2024 yilinda ayni gun icinde ayni hasta birden fazla hizmet almis mi?")

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["same_day_multi_service_patient_count"]
    assert plan.dimensions == []

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "WITH qualifying_patient_days AS" in built.sql
    assert "COUNT(DISTINCT HizmetAdi) > 1" in built.sql
    assert "GROUP BY HizmetAdi" not in built.sql

    by_branch = _plan(
        "2024 yilinda ayni gun icinde ayni hasta birden fazla hizmet alanlari subelere gore kir"
    )
    assert by_branch.metrics == ["same_day_multi_service_patient_count"]
    assert by_branch.dimensions == ["SubeAdi"]
    by_branch_sql = DeterministicSQLBuilder().build(by_branch)
    assert not isinstance(by_branch_sql, UnsupportedPlan)
    assert "patient_day_services AS" in by_branch_sql.sql
    assert "JOIN qualifying_patient_days" in by_branch_sql.sql
    assert "GROUP BY SubeAdi" in by_branch_sql.sql
    assert "COUNT(DISTINCT CONCAT" not in by_branch_sql.sql


def test_same_day_multi_doctor_patient_routes_to_relationship_cte():
    plan = _plan("2024 yilinda ayni gun ayni hasta birden fazla doktorla islem gormus mu?")

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["same_day_multi_doctor_patient_count"]
    assert plan.dimensions == []

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "WITH qualifying_patient_days AS" in built.sql
    assert "COUNT(DISTINCT DoktorId) > 1" in built.sql
    assert "GROUP BY DoktorId" not in built.sql

    by_branch = _plan(
        "2024 yilinda ayni gun ayni hasta birden fazla doktorla islem gormus olanlari subelere gore kir"
    )
    assert by_branch.metrics == ["same_day_multi_doctor_patient_count"]
    assert by_branch.dimensions == ["SubeAdi"]
    by_branch_sql = DeterministicSQLBuilder().build(by_branch)
    assert not isinstance(by_branch_sql, UnsupportedPlan)
    assert "patient_day_doctors AS" in by_branch_sql.sql
    assert "JOIN qualifying_patient_days" in by_branch_sql.sql
    assert "GROUP BY SubeAdi" in by_branch_sql.sql


def test_patient_appointment_span_days_routes_to_cte_and_top_patients():
    plan = _plan("2024 yilinda bir hastanin ilk ve son randevusu arasinda kac gun gecmis?")

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["patient_appointment_span_days"]
    assert plan.dimensions == []

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "WITH patient_spans AS" in built.sql
    assert "DATEDIFF(day" in built.sql
    assert "AVG(CAST(span_days AS FLOAT)) AS patient_appointment_span_days" in built.sql
    assert "GROUP BY SubeAdi" not in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, plan, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True

    top_patients = _plan("2024 yilinda en yuksek farki olan 10 hastayi listele.")
    assert top_patients.metrics == ["patient_appointment_span_days"]
    assert top_patients.limit == 10
    top_sql = DeterministicSQLBuilder().build(top_patients)
    assert not isinstance(top_sql, UnsupportedPlan)
    assert "SELECT TOP (10) HastaId AS HastaId" in top_sql.sql
    assert "ORDER BY patient_appointment_span_days DESC" in top_sql.sql


@pytest.mark.parametrize(
    ("question", "dimension"),
    [
        ("Şube adı bazında hasta ilk-son randevu gün farkını göster.", "SubeAdi"),
        (
            "Bölüm adı raporlama bazında hasta ilk-son randevu gün farkını göster.",
            "GenelRandevuBolumAdi",
        ),
        ("Randevu tipi bazında hasta ilk-son randevu gün farkını göster.", "RandevuTipiAdi"),
        ("Hasta ilk-son randevu gün farkını randevu türü kırılımında göster.", "RandevuTipiAdi"),
    ],
)
def test_patient_span_keeps_explicit_business_label_breakdowns(question, dimension):
    plan = _plan(question)

    assert plan.metrics == ["patient_appointment_span_days"]
    assert plan.dimensions == [dimension]
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert f"GROUP BY {dimension}, HastaId" in built.sql
    assert f"GROUP BY {dimension}\n" in built.sql


def test_multi_period_patient_overlap_uses_or_scoped_presence_cte():
    plan = _plan("Hem 2023 hem 2024 icinde islem goren hastalari say.")

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["multi_period_patient_overlap_count"]
    assert len(plan.date_filters) == 2

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "WITH patient_period_presence AS" in built.sql
    assert "overlap_patients AS" in built.sql
    assert "in_baseline_period = 1 AND in_current_period = 1" in built.sql
    assert ") OR (" in built.sql
    assert "SELECT COUNT(*) AS multi_period_patient_overlap_count" in built.sql
    compliance = PlanComplianceValidator().check(
        built.sql, plan, built.expected_aliases, deterministic=True
    )
    assert compliance.compliant is True

    by_branch = _plan("Hem 2023 hem 2024 icinde islem goren hastalari subelere gore kir.")
    assert by_branch.metrics == ["multi_period_patient_overlap_count"]
    assert by_branch.dimensions == ["SubeAdi"]
    by_branch_sql = DeterministicSQLBuilder().build(by_branch)
    assert not isinstance(by_branch_sql, UnsupportedPlan)
    assert "JOIN overlap_patients" in by_branch_sql.sql
    assert "GROUP BY v.SubeAdi" in by_branch_sql.sql


def test_two_month_increase_request_builds_grouped_period_comparison():
    plan = _plan("2024 Mayis-Haziran kapsaminda en cok artan 5 sube hangisi?")

    assert plan.analysis_type == "period_comparison"
    assert plan.dimensions == ["SubeAdi"]
    assert plan.limit == 5
    assert len(plan.periods) == 2
    assert "period_change_direction:increase" in plan.derived_calculations

    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert "SELECT TOP (5)" in built.sql
    assert "GROUP BY SubeAdi" in built.sql
    assert "HAVING" in built.sql
    assert "ORDER BY" in built.sql
    assert built.sql.rstrip().endswith("DESC;")


def test_singular_service_ranking_and_first_doctor_list_are_aggregates():
    service = _plan("2024 yilinda en cok kullanilan hizmet hangisi?")
    assert service.limit == 1
    assert service.dimensions == ["HizmetAdi"]
    service_sql = DeterministicSQLBuilder().build(service)
    assert not isinstance(service_sql, UnsupportedPlan)
    assert "SELECT TOP (1)" in service_sql.sql
    assert "GROUP BY HizmetAdi" in service_sql.sql

    doctors = _plan("2024 yilinda ilk 10 doktoru listele")
    assert doctors.analysis_type in {"ranking", "top_n", "distribution"}
    assert doctors.limit == 10
    assert doctors.dimensions == ["GenelRandevuKaynakAdi"]
    doctor_sql = DeterministicSQLBuilder().build(doctors)
    assert not isinstance(doctor_sql, UnsupportedPlan)
    assert "SELECT TOP (10)" in doctor_sql.sql
    assert "GROUP BY GenelRandevuKaynakAdi" in doctor_sql.sql
    assert "Id AS Id" not in doctor_sql.sql


def test_trend_builder_renders_every_verified_metric():
    plan = (
        QueryPlanner()
        .build_plan(
            "Aylik randevu egilimini goster",
            QueryAnalyzer().analyze("Aylik randevu egilimini goster"),
            tables=[],
            views=[VIEW],
        )
        .model_copy(update={"metrics": ["appointment_count", "completed_appointment_rate"]})
    )
    built = DeterministicSQLBuilder()._trend(plan)
    assert isinstance(built, DeterministicSQL)
    assert "AS appointment_count" in built.sql
    assert "AS completed_appointment_rate" in built.sql
    assert built.expected_aliases == [
        "period_start",
        "appointment_count",
        "completed_appointment_rate",
    ]


def test_period_comparison_renders_a_column_pair_per_metric():
    """Multi-metric comparison ("2024 ve 2025 için toplam, gerçekleşen ve
    gelmeyen randevuyu karşılaştır") builds one current_/baseline_ pair per
    metric. It used to be rejected outright and surfaced as "Yanıt
    Oluşturulamadı" (Codex live UI testing, 2026-07-31). The PRIMARY metric
    keeps the canonical aliases so the PeriodComparisonResult contract and its
    renderer are unchanged."""
    plan = _plan("Bu ay ile gecen ayin randevu sayilarini karsilastir.").model_copy(
        update={
            "metrics": [
                "completed_appointment_count",
                "appointment_count",
                "no_show_count",
            ]
        }
    )
    built = DeterministicSQLBuilder()._period_comparison(plan, adaptive_retry=False)
    assert isinstance(built, DeterministicSQL)
    # The plain total is the headline pair, whatever order the planner used.
    assert "AS current_period_count" in built.sql
    assert "AS baseline_period_count" in built.sql
    for metric_id in ("completed_appointment_count", "no_show_count"):
        assert f"AS current_{metric_id}" in built.sql
        assert f"AS baseline_{metric_id}" in built.sql


def test_period_comparison_scopes_composite_rate_in_scalar_subqueries():
    """A composite rate cannot be wrapped in another conditional aggregate.
    It is evaluated in a read-only scalar subquery for each period instead, so
    the requested metric is preserved without illegal nested aggregates."""
    plan = _plan("Bu ay ile gecen ayin randevu sayilarini karsilastir.").model_copy(
        update={"metrics": ["appointment_count", "completed_appointment_rate"]}
    )
    built = DeterministicSQLBuilder()._period_comparison(plan, adaptive_retry=False)
    assert isinstance(built, DeterministicSQL)
    assert built.skipped_metrics == []
    assert "AS current_completed_appointment_rate" in built.sql
    assert "AS baseline_completed_appointment_rate" in built.sql
    assert built.sql.count("SELECT 100.0 * SUM(CASE") >= 2
    # No aggregate directly wrapping another aggregate.
    assert not re.search(
        r"(?:SUM|COUNT|AVG)\s*\([^()]*?(?:SUM|COUNT|AVG)\s*\(",
        built.sql.replace("CASE WHEN", ""),
    )


def test_three_period_breakdown_renders_two_and_three_metric_requests():
    plan = QueryPlan(
        question="2023, 2024 ve 2025 için sayı, süre ve gelmeme oranı",
        output_table="dbo.vw_RandevuRaporu",
        fact_table="dbo.vw_RandevuRaporu",
        analysis_type="period_comparison",
        metrics=["appointment_count", "appointment_duration_average", "no_show_rate"],
        periods=[
            PeriodPlan(
                label=str(year),
                start_inclusive=f"{year}-01-01",
                end_exclusive=f"{year + 1}-01-01",
                column="BaslangicTarihi",
            )
            for year in (2023, 2024, 2025)
        ],
    )

    built = DeterministicSQLBuilder()._multi_period_breakdown(plan)

    assert isinstance(built, DeterministicSQL)
    assert built.sql.count("AS appointment_count") == 3
    assert built.sql.count("AS appointment_duration_average") == 3
    assert built.sql.count("AS no_show_rate") == 3
    assert built.expected_aliases == [
        "period_label",
        "appointment_count",
        "appointment_duration_average",
        "no_show_rate",
    ]
    assert SQLValidator().validate(built.sql).valid


# ═══════════════════════ Compliance: metric/dimension coverage ═══════════════


def test_compliance_flags_missing_metric_in_multi_metric_plan():
    plan = _plan(
        "Subelere gore randevu sayisi, gerceklesme orani ve ortalama randevu suresini karsilastir"
    )
    sql = (
        "SELECT SubeAdi AS SubeAdi, "
        "AVG(CAST(RandevuSuresi AS FLOAT)) AS appointment_duration_average "
        "FROM dbo.vw_RandevuRaporu GROUP BY SubeAdi;"
    )
    result = PlanComplianceValidator().check(sql, plan)
    assert result.compliant is False
    assert "appointment_count" in result.missing_metrics
    assert "completed_appointment_rate" in result.missing_metrics
    assert "appointment_duration_average" not in result.missing_metrics


def test_compliance_passes_when_all_metrics_present():
    plan = _plan(
        "Subelere gore randevu sayisi, gerceklesme orani ve ortalama randevu suresini karsilastir"
    )
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    result = PlanComplianceValidator().check(
        built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
    )
    assert result.compliant is True
    assert result.missing_metrics == []


def test_compliance_single_metric_plan_unaffected_by_metric_coverage_check():
    plan = _plan("Subelere gore gelmeme oranlari nedir?")
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    result = PlanComplianceValidator().check(
        built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
    )
    assert result.compliant is True


# ═══════════════════════ Bounded repair diagnostics ═══════════════════════


@pytest.mark.asyncio
async def test_metric_coverage_gap_blocks_after_bounded_llm_repair():
    plan = _plan("Subelere gore randevu sayisini goster").model_copy(
        update={"metrics": ["appointment_count", "protocol_state_based_completion"]}
    )
    provider = _Provider()
    service = SQLService(provider, _Parser(), SQLValidator())
    with pytest.raises(Exception) as exc_info:
        await service.generate_sql("prompt", query_plan=plan)
    assert provider.calls == 2
    assert "protocol_state_based_completion" in str(exc_info.value)


@pytest.mark.asyncio
async def test_metric_coverage_gap_can_be_repaired_once_by_llm():
    plan = _plan("Subelere gore randevu sayisini goster").model_copy(
        update={"metrics": ["appointment_count", "protocol_state_based_completion"]}
    )

    class RepairProvider:
        calls = 0

        async def generate(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                content = (
                    "SELECT SubeAdi AS SubeAdi, COUNT(*) AS appointment_count "
                    "FROM dbo.vw_RandevuRaporu GROUP BY SubeAdi;"
                )
            else:
                content = (
                    "SELECT SubeAdi AS SubeAdi, COUNT(*) AS appointment_count, "
                    "SUM(CASE WHEN ProtokolIslemState IS NOT NULL THEN 1 ELSE 0 END) "
                    "AS protocol_state_based_completion "
                    "FROM dbo.vw_RandevuRaporu GROUP BY SubeAdi;"
                )
            return LLMResponse(content=content, model="fake", latency_ms=1.0)

        def get_metadata(self):
            return {"provider": "fake"}

    provider = RepairProvider()
    service = SQLService(provider, _Parser(), SQLValidator())
    generated = await service.generate_sql("prompt", query_plan=plan)
    assert provider.calls == 2
    assert generated.sql_source == "repaired_llm"
    assert generated.missing_metrics_after == []
