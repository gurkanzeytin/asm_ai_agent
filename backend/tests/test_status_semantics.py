"""AI-INTELLIGENCE-011 tests: verified status semantics, cohort distribution,
validation typing, follow-up negation, Turkish presentation, and the comparison
contract. Deterministic — no LLM, no database.
"""

from datetime import UTC, datetime

import pytest

from app.analytics.result_contracts import CohortResult, PeriodComparisonResult
from app.analytics.result_reasoning import ResultReasoner
from app.analytics.result_validation import ResultValidator
from app.application_models.workflow_models import QueryResult
from app.context.models import ConversationContext
from app.context.resolver import ContextResolver
from app.database_intelligence.models import ViewMetadata
from app.planning.models import QueryPlan
from app.planning.planner import QueryPlanner
from app.reporting.presentation import format_number, format_percent, label_for
from app.reporting.report_classifier import ReportType
from app.reporting.template_renderer import TemplateReportRenderer
from app.semantics import catalog
from app.services.deterministic_sql_builder import (
    VERIFIED_STATUS_VALUES,
    DeterministicSQLBuilder,
    UnsupportedPlan,
)
from app.services.query_analyzer import QueryAnalyzer

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
STATUS_PREFIXES = ("completed", "checked_in", "no_show", "in_progress", "waiting")


@pytest.fixture(scope="module")
def analyzer():
    return QueryAnalyzer()


@pytest.fixture(scope="module")
def planner():
    return QueryPlanner()


def plan_for(planner, analyzer, question):
    return planner.build_plan(question, analyzer.analyze(question), tables=[], views=[VIEW])


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


# ══════════════════════════ Status mapping ══════════════════════════════


def test_exactly_five_verified_statuses():
    assert VERIFIED_STATUS_VALUES == {
        "completed": "Gerçekleşti",
        "checked_in": "Giriş Yapılmış",
        "no_show": "Gelmedi",
        "in_progress": "İşlem Sürmekte",
        "waiting": "Beklemede",
    }


def test_no_iptal_anywhere_in_metric_catalog():
    for metric in catalog.load_metric_catalog().metrics:
        assert "cancelled" not in metric.id, metric.id
        assert "İptal" not in (metric.formula or ""), metric.id
        assert "iptal" not in " ".join(metric.synonyms), metric.id


def test_all_status_metrics_exist_with_nullif():
    by_id = catalog.load_metric_catalog().by_id()
    for prefix in STATUS_PREFIXES:
        rate_id = f"{prefix}_rate" if f"{prefix}_rate" in by_id else f"{prefix}_appointment_rate"
        assert rate_id in by_id, rate_id
        assert "NULLIF" in (by_id[rate_id].formula or ""), rate_id


def test_status_filter_no_longer_maps_iptal():
    from app.semantics.view_mapping import resolve_status_filter

    assert resolve_status_filter("iptal edilen randevular") is None
    assert resolve_status_filter("gelmeyen hastalar") == "RandevuDurumu = 'Gelmedi'"


# ══════════════════════════ Cohort ═══════════════════════════════════════


def _cohort_plan(planner, analyzer):
    return plan_for(planner, analyzer, "Randevusunu son dakika alanların gelme durumu nasıl?")


def test_cohort_sql_uses_between_0_and_24(planner, analyzer):
    built = DeterministicSQLBuilder().build(_cohort_plan(planner, analyzer))
    assert not isinstance(built, UnsupportedPlan)
    assert "DATEDIFF(hour, CreatedDate, BaslangicTarihi) BETWEEN 0 AND 24" in built.sql


def test_cohort_sql_produces_all_five_statuses_and_no_cancelled(planner, analyzer):
    built = DeterministicSQLBuilder().build(_cohort_plan(planner, analyzer))
    for prefix in STATUS_PREFIXES:
        assert f"{prefix}_count" in built.expected_aliases
        assert f"{prefix}_rate" in built.expected_aliases
    assert "cancelled_count" not in built.expected_aliases
    assert "İptal" not in built.sql


def test_cohort_contract_has_no_cancelled_fields():
    fields = set(CohortResult.model_fields)
    assert "cancelled_count" not in fields
    assert "cancelled_rate" not in fields
    for prefix in STATUS_PREFIXES:
        assert f"{prefix}_rate" in fields


def test_cohort_rate_sum_validation_flags_gaps():
    row = {
        "cohort_total_count": 1000,
        "completed_rate": 40.0,
        "checked_in_rate": 10.0,
        "no_show_rate": 10.0,
        "in_progress_rate": 10.0,
        "waiting_rate": 10.0,
    }
    row.update({f"{p}_count": 100 for p in STATUS_PREFIXES})
    outcome = ResultReasoner().reason(
        _result(list(row), [row]), QueryPlan(question="q"), result_schema="CohortResult"
    )
    assert any("%100" in finding for finding in outcome.findings)


def test_cohort_reasoning_full_distribution_turkish():
    row = {
        "cohort_total_count": 678866,
        "completed_count": 498287, "completed_rate": 73.4,
        "checked_in_count": 74000, "checked_in_rate": 10.9,
        "no_show_count": 58382, "no_show_rate": 8.6,
        "in_progress_count": 33943, "in_progress_rate": 5.0,
        "waiting_count": 14254, "waiting_rate": 2.1,
    }
    outcome = ResultReasoner().reason(
        _result(list(row), [row]), QueryPlan(question="q"), result_schema="CohortResult"
    )
    joined = " ".join(outcome.findings)
    assert "678.866" in joined
    assert "%73,4" in joined
    assert "iptal" not in joined.lower()


# ══════════════════════════ Validation typing ════════════════════════════


def test_count_fields_never_percentage_checked():
    report = ResultValidator().validate(
        _result(
            ["cohort_total_count", "completed_count", "no_show_count"],
            [{"cohort_total_count": 678866, "completed_count": 498287, "no_show_count": 58382}],
        )
    )
    assert not any(f.check == "percentage_range" for f in report.findings)


def test_rate_fields_are_percentage_checked():
    report = ResultValidator().validate(
        _result(["no_show_rate"], [{"no_show_rate": 140.0}])
    )
    assert any(f.check == "percentage_range" for f in report.findings)


def test_rate_point_change_allows_negative_values():
    report = ResultValidator().validate(
        _result(["rate_point_change"], [{"rate_point_change": -12.5}])
    )
    assert not any(f.check == "percentage_range" for f in report.findings)


def test_percentage_change_is_unbounded():
    report = ResultValidator().validate(
        _result(["percentage_change"], [{"percentage_change": 250.0}])
    )
    assert not any(f.check == "percentage_range" for f in report.findings)


# ══════════════════════════ Follow-up negation ═══════════════════════════


def test_negation_followup_inherits_and_inverts(planner, analyzer):
    context = ConversationContext(
        session_id="t",
        last_question="Bu aralar hangi şubede gelmeme oranı artmış?",
    )
    resolution = ContextResolver().resolve("Peki artmamış olanlar?", context)
    assert resolution.applied
    assert "artmamış" in resolution.resolved_question
    plan = plan_for(planner, analyzer, resolution.resolved_question)
    assert plan.analysis_type == "anomaly_comparison"
    assert "no_show_rate" in plan.metrics  # metric inheritance
    assert plan.dimensions == ["SubeAdi"]  # dimension inheritance
    assert plan.baseline_period == "previous_30_days"  # period inheritance
    assert plan.order == "ASC"  # comparison direction inversion
    assert any("rate_point_change <= 0" in d for d in plan.derived_calculations)


def test_negation_followup_without_context_is_untouched():
    resolution = ContextResolver().resolve(
        "Peki artmamış olanlar?", ConversationContext(session_id="t")
    )
    assert not resolution.applied


def test_cancel_negation_followup_still_limitation(planner, analyzer):
    plan = plan_for(planner, analyzer, "Bu aralar hangi şubede iptaller patlamamış?")
    assert plan.answerable is False
    assert "İptal" in (plan.answerability_reason or "")


# ══════════════════════════ Turkish presentation ═════════════════════════


def test_number_and_percent_formats():
    assert format_number(678866) == "678.866"
    assert format_percent(73.409332622343) == "%73,4"
    assert format_percent(8.6) == "%8,6"


def test_labels_are_turkish():
    assert label_for("cohort_total_count") == "Son Dakika Randevusu"
    assert label_for("no_show_rate") == "Gelmeme Oranı"
    assert label_for("rate_point_change") == "Oran Farkı"


def test_cohort_template_renders_turkish_cards():
    row = {
        "cohort_total_count": 678866,
        "completed_count": 498287, "completed_rate": 73.4,
        "checked_in_count": 74000, "checked_in_rate": 10.9,
        "no_show_count": 58382, "no_show_rate": 8.6,
        "in_progress_count": 33943, "in_progress_rate": 5.0,
        "waiting_count": 14254, "waiting_rate": 2.1,
    }
    rendered = TemplateReportRenderer().render(
        ReportType.SINGLE_ROW, _result(list(row), [row])
    )
    assert rendered is not None
    assert rendered.template_name == "cohort"
    assert "678.866" in rendered.markdown
    assert "%73,4" in rendered.markdown
    assert "Gelmeme Oranı" in rendered.markdown
    assert "Cohort Total Count" not in rendered.markdown
    assert "iptal" not in rendered.markdown.lower()


def test_no_english_report_strings_left():
    from app.insights import templates

    assert templates.build_title.__module__  # module imports
    assert "Comparison Analysis" not in open(
        templates.__file__, encoding="utf-8"
    ).read()


# ══════════════════════════ Comparison contract ══════════════════════════


def test_explicit_month_year_pair_parses_two_periods(analyzer):
    analysis = analyzer.analyze("2023 Eylül ile 2023 Ekim randevu sayılarını karşılaştır.")
    assert len(analysis.detected_dates) == 2
    starts = {str(d.start_date) for d in analysis.detected_dates}
    assert starts == {"2023-09-01", "2023-10-01"}


def test_builder_uses_explicit_periods_with_labels(planner, analyzer):
    plan = plan_for(
        planner, analyzer, "2023 Eylül ile 2023 Ekim randevu sayılarını karşılaştır."
    )
    built = DeterministicSQLBuilder().build(plan)
    assert not isinstance(built, UnsupportedPlan)
    assert built.result_schema == "PeriodComparisonResult"
    assert "2023-09-01" in built.sql and "2023-10-01" in built.sql
    assert "current_period_label" in built.expected_aliases
    assert "baseline_period_label" in built.expected_aliases


def test_comparison_contract_completeness():
    complete = PeriodComparisonResult(
        current_period_count=10, baseline_period_count=6, absolute_change=4
    )
    incomplete = PeriodComparisonResult(current_period_count=6)
    assert complete.is_complete()
    assert not incomplete.is_complete()


def test_single_value_never_renders_comparison_template():
    row = {"current_period_count": 6, "baseline_period_count": None, "absolute_change": None}
    rendered = TemplateReportRenderer().render(
        ReportType.SINGLE_ROW, _result(list(row), [row])
    )
    assert rendered is not None
    assert rendered.template_name == "comparison_fallback"
    assert "iki ayrı dönem sonucu oluşturulamadı" in rendered.markdown


def test_complete_comparison_renders_turkish_summary():
    row = {
        "current_period_label": "2023 Ekim",
        "baseline_period_label": "2023 Eylül",
        "current_period_count": 5200,
        "baseline_period_count": 4800,
        "absolute_change": 400,
        "percentage_change": 8.3,
    }
    rendered = TemplateReportRenderer().render(
        ReportType.SINGLE_ROW, _result(list(row), [row])
    )
    assert rendered.template_name == "comparison"
    assert "Dönem Karşılaştırması" in rendered.markdown
    assert "5.200" in rendered.markdown
    assert "%8,3" in rendered.markdown
    assert "Comparison" not in rendered.title


# ══════════════════════════ No forced winner ═════════════════════════════


def test_anomaly_without_increase_declares_no_winner():
    rows = [
        {"SubeAdi": "Merkez", "current_period_count": 900, "baseline_period_count": 880,
         "rate_point_change": 0.0},
        {"SubeAdi": "Gebze", "current_period_count": 40, "baseline_period_count": 45,
         "rate_point_change": -1.2},
    ]
    rendered = TemplateReportRenderer().render(
        ReportType.TABLE, _result(list(rows[0]), rows)
    )
    assert rendered.template_name == "anomaly"
    assert "artış tespit edilmedi" in rendered.markdown
    assert "Gebze" not in rendered.markdown.split("tespit edilmedi")[0]
    outcome = ResultReasoner().reason(
        _result(list(rows[0]), rows), QueryPlan(question="q"), result_schema="AnomalyResult"
    )
    assert any("artış tespit edilmedi" in f for f in outcome.findings)


def test_anomaly_with_increase_names_top_group():
    rows = [
        {"SubeAdi": "Merkez", "current_period_count": 900, "baseline_period_count": 880,
         "rate_point_change": 3.4},
        {"SubeAdi": "Gebze", "current_period_count": 400, "baseline_period_count": 450,
         "rate_point_change": -1.2},
    ]
    rendered = TemplateReportRenderer().render(
        ReportType.TABLE, _result(list(rows[0]), rows)
    )
    assert "Merkez" in rendered.markdown
    assert "%3,4" in rendered.markdown


# ══════════════════════════ Regression (canlı sorular) ═══════════════════


@pytest.mark.parametrize(
    "question,expected_type,answerable",
    [
        ("Randevusunu son dakika alanların gelme durumu nasıl?", "cohort_analysis", True),
        ("Bu aralar hangi şubede iptaller patlamış?", None, False),
        ("Bu aralar hangi şubede gelmeme oranı artmış?", "anomaly_comparison", True),
        ("2023 Eylül ile 2023 Ekim randevu sayılarını karşılaştır.", "period_comparison", True),
        ("Telefon bilgisi eksik kaç hasta var?", None, False),
        ("Doktorlar arasında çok fark var mı?", "variance_analysis", True),
    ],
)
def test_live_acceptance_regression(planner, analyzer, question, expected_type, answerable):
    plan = plan_for(planner, analyzer, question)
    assert plan.answerable is answerable, question
    if answerable and expected_type:
        assert plan.analysis_type == expected_type, question
        built = DeterministicSQLBuilder().build(plan)
        assert not isinstance(built, UnsupportedPlan), question
        assert "İptal" not in built.sql
