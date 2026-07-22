# ruff: noqa: E501

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.analytics.result_contracts import TypedResultNormalizer
from app.analytics.result_reasoning import ResultReasoner
from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import ViewMetadata
from app.llm.schemas import LLMResponse
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.semantics import catalog
from app.services.deterministic_sql_builder import DeterministicSQLBuilder, UnsupportedPlan
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
    generated = await service.generate_sql("prompt", query_plan=_plan("Subelere gore gelmeme oranlari nedir?"))
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


def test_metric_sql_mapping_excludes_unverified_metrics():
    mapping = DeterministicSQLBuilder().metric_sql_map()
    assert mapping["appointment_count"] == "COUNT(*)"
    assert "patient_id_mismatch_count" not in mapping
    for metric in catalog.load_metric_catalog().metrics:
        if metric.status == "requires_verified_mapping":
            assert metric.id not in mapping


def test_cohort_sql_generation_and_contract():
    built = DeterministicSQLBuilder().build(_plan("Randevusunu son dakika alanlarin gelme durumu nasil?"))
    assert not isinstance(built, UnsupportedPlan)
    assert built.result_schema == "CohortResult"
    assert "DATEDIFF(hour, CreatedDate, BaslangicTarihi) BETWEEN 0 AND 24" in built.sql
    assert "cohort_total_count" in built.expected_aliases
    assert "HastaAdi" not in built.sql


def test_period_pair_sql_generation():
    built = DeterministicSQLBuilder().build(_plan("Bu ay ile gecen ayin randevu sayilarini karsilastir."))
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
        [{"cohort_total_count": Decimal("10"), "completed_rate": Decimal("80.5"), "cancelled_rate": None, "no_show_rate": Decimal("5")}],
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
        ["group_count", "total_appointments", "average_appointments", "minimum_appointments", "maximum_appointments", "max_to_average_ratio", "top_10_percent_share"],
        [{"group_count": 5, "total_appointments": 100, "average_appointments": 20, "minimum_appointments": 5, "maximum_appointments": 50, "max_to_average_ratio": 2.5, "top_10_percent_share": 40}],
    )
    outcome = ResultReasoner().reason(result, QueryPlan(question="q"), result_schema="VarianceResult")
    assert any("ortalama" in finding for finding in outcome.findings)


def test_adaptive_retry_updates_deterministic_windows():
    built = DeterministicSQLBuilder().build(_plan("Randevusunu son dakika alanlarin gelme durumu nasil?"), adaptive_retry=True)
    assert not isinstance(built, UnsupportedPlan)
    assert "BETWEEN 0 AND 48" in built.sql
    period = DeterministicSQLBuilder().build(_plan("Bu aralar hangi subede gelmeme orani artmis?"), adaptive_retry=True)
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
        ("Randevusunu son dakika alanlarin gelme durumu nasil?", "CohortResult", "cohort_total_count"),
        ("Bu aralar hangi subede gelmeme orani artmis?", "AnomalyResult", "rate_point_change"),
        ("Doktorlar arasinda cok fark var mi?", "VarianceResult", "top_10_percent_share"),
        ("Bu ay ile gecen ayin randevu sayilarini karsilastir.", "PeriodComparisonResult", "percentage_change"),
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
        "Subelere gore randevu sayisi, gerceklesme orani ve ortalama randevu "
        "suresini karsilastir"
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


def test_trend_builder_rejects_multi_metric_explicitly():
    plan = QueryPlanner().build_plan(
        "Aylik randevu egilimini goster",
        QueryAnalyzer().analyze("Aylik randevu egilimini goster"),
        tables=[],
        views=[VIEW],
    ).model_copy(update={"metrics": ["appointment_count", "completed_appointment_rate"]})
    built = DeterministicSQLBuilder()._trend(plan)
    assert isinstance(built, UnsupportedPlan)
    assert "multi-metric" in built.reason


def test_period_comparison_rejects_multi_metric_explicitly():
    plan = _plan("Bu ay ile gecen ayin randevu sayilarini karsilastir.").model_copy(
        update={"metrics": ["appointment_count", "completed_appointment_rate"]}
    )
    built = DeterministicSQLBuilder()._period_comparison(plan, adaptive_retry=False)
    assert isinstance(built, UnsupportedPlan)
    assert "multi-metric" in built.reason


# ═══════════════════════ Compliance: metric/dimension coverage ═══════════════


def test_compliance_flags_missing_metric_in_multi_metric_plan():
    plan = _plan(
        "Subelere gore randevu sayisi, gerceklesme orani ve ortalama randevu "
        "suresini karsilastir"
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
        "Subelere gore randevu sayisi, gerceklesme orani ve ortalama randevu "
        "suresini karsilastir"
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
async def test_metric_coverage_gap_falls_through_to_llm_without_raising():
    plan = _plan("Subelere gore randevu sayisini goster").model_copy(
        update={"metrics": ["appointment_count", "protocol_state_based_completion"]}
    )
    provider = _Provider()
    service = SQLService(provider, _Parser(), SQLValidator())
    generated = await service.generate_sql("prompt", query_plan=plan)
    assert provider.calls >= 1
    assert generated.sql_source in ("llm", "repaired_llm")
    assert generated.repair_attempted is True
    assert "protocol_state_based_completion" in generated.missing_metrics_before
