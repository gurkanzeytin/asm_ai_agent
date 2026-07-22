"""Regression coverage for year-only follow-ups and scalar aggregate KPIs."""

from datetime import date, datetime

import pytest

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.models import ResultShape
from app.application_models.workflow_models import QueryResult
from app.context.models import ConversationContext
from app.context.resolver import ContextResolver
from app.planning.models import DateFilterPlan, PlannedMetric, QueryPlan
from app.services.answerability import AnswerabilityGuard
from app.services.deterministic_sql_builder import DeterministicSQLBuilder
from app.services.query_analyzer import QueryAnalyzer

YEAR_FORMS = [
    "2024 yılının?",
    "2024 yılı?",
    "2024 için?",
    "2024'te?",
    "Peki 2024?",
    "Geçen yılın?",
    "Bir önceki yıl?",
    "Önceki yıl?",
    "2023'e göre?",
    "2024 olanı?",
]


def _context() -> ConversationContext:
    return ConversationContext(
        session_id="same-session",
        date_expression="2025 yilinin",
        entity_types=["Appointment"],
        metrics=["appointment_duration_average"],
        analysis_type="summary",
        last_question="2025 yilinin randevu surelerinin raporunu cikar",
    )


@pytest.mark.parametrize("question", YEAR_FORMS)
def test_year_only_forms_are_genuine_followups_with_typed_context(question):
    resolution = ContextResolver().resolve(question, _context())

    assert resolution.follow_up_detected is True
    assert resolution.context_applied is True
    assert resolution.clarification_needed is False
    assert resolution.resolved_signals.metrics == ["appointment_duration_average"]
    assert "randevu surelerinin" in resolution.resolved_question


def test_explicit_year_replaces_inherited_year_and_previous_year_is_relative_to_anchor():
    explicit = ContextResolver().resolve("2024 yılının?", _context())
    relative = ContextResolver().resolve("Bir önceki yıl?", _context())

    assert "2024" in explicit.resolved_question
    assert "2025" not in explicit.resolved_question
    assert "date" in explicit.overridden_fields
    assert "2024" in relative.resolved_question


def test_year_fragment_without_context_requests_clarification_not_out_of_scope():
    resolution = ContextResolver().resolve(
        "2024 yılının?", ConversationContext(session_id="new-session")
    )

    assert resolution.clarification_needed is True
    assert resolution.follow_up_detected is False
    assert "hangi randevu analizini" in (resolution.clarification_question or "")


def test_complete_new_question_and_unrelated_short_question_do_not_inherit_metric():
    resolver = ContextResolver()
    complete = resolver.resolve(
        "2024 yılındaki kadın hastaların yaş dağılımı?", _context()
    )
    unrelated = resolver.resolve("Faturalar?", _context())

    assert complete.follow_up_detected is False
    assert complete.resolved_signals.metrics == []
    assert unrelated.follow_up_detected is False
    assert unrelated.resolved_signals.metrics == []


def test_resolved_context_signals_make_answerability_explicit():
    verdict = AnswerabilityGuard().assess(
        "2024 yilinda randevu surelerinin raporunu cikar",
        [
            "inherited_entity:Appointment",
            "inherited_metric:appointment_duration_average",
            "explicit_date:2024",
        ],
    )

    assert verdict.answerable is True
    assert verdict.reason == "resolved_context_detected"
    assert "explicit_date:2024" in verdict.signals


def test_calendar_year_parser_and_sql_use_half_open_upper_bound():
    analyzer = QueryAnalyzer(today=date(2026, 7, 22))
    span = analyzer.analyze("2024 yılının randevu süreleri").detected_dates[0]
    assert span.start_date == date(2024, 1, 1)
    assert span.end_date == date(2024, 12, 31)

    plan = QueryPlan(
        question="2024 yılının randevu süreleri",
        fact_entity="Appointment",
        fact_table="dbo.vw_RandevuRaporu",
        metrics=["appointment_duration_average"],
        analysis_type="average",
        date_filters=[
            DateFilterPlan(
                expression="2024 yilinin",
                start_date="2024-01-01",
                end_date="2024-12-31",
                column="BaslangicTarihi",
            )
        ],
    )
    sql = DeterministicSQLBuilder().build(plan).sql
    assert "BaslangicTarihi >= '2024-01-01'" in sql
    assert "BaslangicTarihi < DATEADD(day, 1, '2024-12-31')" in sql
    assert "AVG(CAST(RandevuSuresi AS FLOAT))" in sql
    assert "90" not in sql


def _result(columns, row):
    return QueryResult(
        columns=columns,
        rows=[row],
        row_count=1,
        execution_time_ms=1,
        success=True,
        executed_at=datetime(2026, 7, 22),
        database_provider="mssql",
    )


def _scalar_plan(metrics):
    return QueryPlan(
        question="randevu metrikleri",
        fact_entity="Appointment",
        metrics=metrics,
        planned_metrics=[
            PlannedMetric(
                metric_id=metric,
                aggregation_type="avg" if "average" in metric else "count_rows",
            )
            for metric in metrics
        ],
        analysis_type="average" if len(metrics) == 1 else "count",
    )


def test_avg_only_scalar_has_one_direct_duration_kpi_without_distribution_artifacts():
    result = AnalyticsEngine().analyze(
        "ortalama randevu süresi",
        _result(["appointment_duration_average"], {"appointment_duration_average": 31.85}),
        plan=_scalar_plan(["appointment_duration_average"]),
        metric_aliases={"appointment_duration_average": "appointment_duration_average"},
    )

    assert result.result_shape == ResultShape.SCALAR_AGGREGATE
    assert result.technical_row_count == 1
    assert result.business_record_count is None
    assert result.aggregate_result is True
    assert result.metrics == {"appointment_duration_average": 31.85}
    assert [kpi.key for kpi in result.displayable_kpis] == ["appointment_duration_average"]
    assert result.displayable_kpis[0].format == "duration"
    assert result.displayable_kpis[0].unit == "dakika"
    assert result.metric_summaries["appointment_duration_average"].total is None


def test_count_and_average_scalar_expose_each_real_business_metric_once():
    result = AnalyticsEngine().analyze(
        "randevu sayısı ve ortalama süresi",
        _result(
            ["appointment_count", "appointment_duration_average"],
            {"appointment_count": 12345, "appointment_duration_average": 31.85},
        ),
        plan=_scalar_plan(["appointment_count", "appointment_duration_average"]),
        metric_aliases={
            "appointment_count": "appointment_count",
            "appointment_duration_average": "appointment_duration_average",
        },
    )

    assert result.result_shape == ResultShape.MULTI_METRIC_SCALAR_AGGREGATE
    assert [kpi.key for kpi in result.displayable_kpis] == [
        "appointment_count",
        "appointment_duration_average",
    ]
    assert "count" not in result.metrics
    assert "median" not in result.metrics


def test_raw_rows_keep_business_record_count():
    result = AnalyticsEngine().analyze(
        "randevuları listele", _result(["Id"], {"Id": 7}), plan=QueryPlan(question="x")
    )
    assert result.result_shape == ResultShape.RAW_RECORD_ROWS
    assert result.business_record_count == 1
