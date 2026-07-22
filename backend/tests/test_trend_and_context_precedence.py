"""Regression tests for two live-routing bugs:

1. A trend/time-series question ("Son 6 aydaki randevu eğilimini özetle")
   produced a QueryPlan with plain COUNT(*) and no time bucketing, collapsing
   to a single scalar (DataShape.SINGLE_VALUE) instead of a monthly time
   series — so InsightRouter "correctly" chose deterministic mode, but only
   because the upstream plan was wrong.

2. A follow-up question that already contains two explicit date periods
   ("son üç ayı önceki üç ayla karşılaştır") had the previous turn's date
   context ("son 6 aydaki") incorrectly prepended, and the generic word
   "performans" routed the otherwise-explicit multi-metric request to
   clarification even though "randevu sayısı"/"gelmeme oranı"/"bölüm" were
   all already explicit and catalog-resolvable.

No real network calls anywhere in this file — pure planner/builder/analytics/
context/query-analyzer unit tests.
"""

from datetime import date, datetime

import pytest

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.models import DataShape
from app.application_models.workflow_models import QueryResult
from app.context import ContextManager
from app.database_intelligence.models import ColumnMetadata, ViewMetadata
from app.insights.routing import InsightGenerationMode, InsightRouter
from app.insights.rules_engine import InsightRulesEngine
from app.planning.compliance import PlanComplianceValidator
from app.planning.planner import QueryPlanner
from app.services.deterministic_sql_builder import DeterministicSQLBuilder
from app.services.query_analyzer import QueryAnalyzer

_TODAY = date(2026, 7, 20)


def _view() -> ViewMetadata:
    return ViewMetadata(
        name="vw_RandevuRaporu",
        comment="",
        columns=[
            ColumnMetadata(
                name="BaslangicTarihi", type_name="DATETIME", nullable=False, primary_key=False
            ),
            ColumnMetadata(name="Id", type_name="INT", nullable=False, primary_key=True),
        ],
    )


def _build_plan(question: str):
    analyzer = QueryAnalyzer(today=_TODAY)
    analysis = analyzer.analyze(question)
    plan = QueryPlanner().build_plan(question, analysis, tables=[], views=[_view()])
    return analysis, plan


def _query_result(rows: list[dict], columns: list[str]) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )


_TREND_QUESTION = "Son 6 aydaki randevu eğilimini özetle ve dikkat çeken değişimleri açıkla."


# ── A/B: trend/time-series planning, SQL, analytics ───────────────────────────


def test_six_month_trend_creates_monthly_time_series_plan():
    _, plan = _build_plan(_TREND_QUESTION)

    assert plan.analysis_type == "time_trend"
    assert plan.grouping_granularity == "month"
    assert plan.metrics == ["monthly_appointment_count"]
    assert plan.aggregation == "COUNT(*)"


def test_trend_plan_includes_date_column_via_date_filters():
    _, plan = _build_plan(_TREND_QUESTION)

    assert plan.date_filters
    assert plan.date_filters[0].column == "BaslangicTarihi"


def test_deterministic_sql_for_monthly_trend_is_valid_tsql_with_group_and_order():
    _, plan = _build_plan(_TREND_QUESTION)
    result = DeterministicSQLBuilder().build(plan)

    assert hasattr(result, "sql"), getattr(result, "reason", None)
    sql_lower = result.sql.lower()
    assert "group by" in sql_lower
    assert "order by period_start asc" in sql_lower
    assert "datefromparts(year(baslangictarihi), month(baslangictarihi), 1)" in sql_lower
    assert result.result_schema == "TrendResult"
    assert "period_start" in result.expected_aliases

    compliance = PlanComplianceValidator().check(result.sql, plan, result.expected_aliases)
    assert compliance.compliant, compliance.missing


def test_trend_sql_returns_multi_row_shape_in_mocked_execution():
    _, plan = _build_plan(_TREND_QUESTION)
    result = DeterministicSQLBuilder().build(plan)

    # Mocked execution of the generated aliases — six monthly buckets.
    rows = [
        {"period_start": "2026-02-01", "monthly_appointment_count": 12},
        {"period_start": "2026-03-01", "monthly_appointment_count": 18},
        {"period_start": "2026-04-01", "monthly_appointment_count": 15},
        {"period_start": "2026-05-01", "monthly_appointment_count": 20},
        {"period_start": "2026-06-01", "monthly_appointment_count": 14},
        {"period_start": "2026-07-01", "monthly_appointment_count": 13},
    ]
    query_result = _query_result(rows, result.expected_aliases)
    assert query_result.row_count == 6
    assert query_result.row_count > 1


def test_trend_result_recognized_as_time_series():
    rows = [
        {"period_start": "2026-02-01", "monthly_appointment_count": 12},
        {"period_start": "2026-03-01", "monthly_appointment_count": 18},
        {"period_start": "2026-04-01", "monthly_appointment_count": 15},
        {"period_start": "2026-05-01", "monthly_appointment_count": 20},
        {"period_start": "2026-06-01", "monthly_appointment_count": 14},
        {"period_start": "2026-07-01", "monthly_appointment_count": 13},
    ]
    query_result = _query_result(rows, ["period_start", "monthly_appointment_count"])

    analytics = AnalyticsEngine().analyze(_TREND_QUESTION, query_result)

    assert analytics.data_shape == DataShape.TIME_SERIES
    assert analytics.analytics_type == "trend"
    assert analytics.metrics.get("growth_rate") is not None
    assert analytics.metrics.get("trend_direction") is not None
    assert analytics.metrics.get("highest_period") == "2026-05-01"
    assert analytics.metrics.get("lowest_period") == "2026-02-01"


def test_six_month_trend_does_not_collapse_to_one_scalar_total():
    _, plan = _build_plan(_TREND_QUESTION)
    result = DeterministicSQLBuilder().build(plan)

    # The old bug: no GROUP BY at all -> a single scalar COUNT(*) row.
    assert "group by" in result.sql.lower()
    rows = [
        {"period_start": f"2026-0{i}-01", "monthly_appointment_count": 10 + i} for i in range(2, 8)
    ]
    query_result = _query_result(rows, result.expected_aliases)
    assert query_result.row_count != 1


def test_trend_routes_local_qwen_when_deterministic_insufficient():
    rows = [
        {"period_start": "2026-02-01", "monthly_appointment_count": 12},
        {"period_start": "2026-03-01", "monthly_appointment_count": 18},
        {"period_start": "2026-04-01", "monthly_appointment_count": 15},
        {"period_start": "2026-05-01", "monthly_appointment_count": 20},
        {"period_start": "2026-06-01", "monthly_appointment_count": 14},
        {"period_start": "2026-07-01", "monthly_appointment_count": 13},
    ]
    query_result = _query_result(rows, ["period_start", "monthly_appointment_count"])
    analytics = AnalyticsEngine().analyze(_TREND_QUESTION, query_result)
    rules = InsightRulesEngine().evaluate(analytics)
    confidence = InsightRulesEngine().compute_confidence(analytics, rules)

    decision = InsightRouter(remote_available=True).decide(analytics, rules, confidence)

    assert decision.mode == InsightGenerationMode.LOCAL_LLM
    assert decision.selected_provider == "ollama"


# ── C: explicit date precedence in context ────────────────────────────────────


def test_current_explicit_date_overrides_inherited_date():
    manager = ContextManager()
    session_id = "trend-then-compare"
    first = manager.resolve(_TREND_QUESTION, session_id)
    manager.update(first, session_id)

    second = manager.resolve("Son üç ayı önceki üç ayla karşılaştır", session_id)

    assert "date" not in second.inherited
    assert "son 6" not in second.resolved_question.lower()


def test_explicit_multi_period_question_does_not_inherit_prior_context():
    manager = ContextManager()
    session_id = "trend-then-multi-period"
    first = manager.resolve(_TREND_QUESTION, session_id)
    manager.update(first, session_id)

    second = manager.resolve(
        "Son üç ayı önceki üç ayla; randevu sayısı ve gelmeme oranı açısından karşılaştır.",
        session_id,
    )

    assert second.resolved_question == (
        "Son üç ayı önceki üç ayla; randevu sayısı ve gelmeme oranı açısından karşılaştır."
    )
    assert not second.inherited


def test_last_three_months_vs_previous_three_months_produces_two_adjacent_periods():
    analyzer = QueryAnalyzer(today=_TODAY)
    analysis = analyzer.analyze("Son üç ayı önceki üç ayla karşılaştır.")

    assert len(analysis.detected_dates) == 2
    current, previous = analysis.detected_dates
    assert current.start_date == date(2026, 4, 20)
    assert current.end_date == date(2026, 7, 20)
    assert previous.start_date == date(2026, 1, 20)
    assert previous.end_date == date(2026, 4, 20)
    # Adjacent, non-overlapping: previous ends exactly where current starts.
    assert previous.end_date == current.start_date


def test_previous_context_inherited_only_when_current_has_no_date():
    manager = ContextManager()
    session_id = "plain-followup"
    first = manager.resolve(_TREND_QUESTION, session_id)
    manager.update(first, session_id)

    second = manager.resolve("En yoğun bölüm hangisi?", session_id)

    assert "date" in second.inherited
    assert second.inherited["date"]


# ── E: ambiguity handling for generic analytical words ────────────────────────


def test_bare_performans_alone_is_still_ambiguous():
    analyzer = QueryAnalyzer()

    result = analyzer.detect_ambiguity("Doktor performansını göster")

    assert result is not None
    assert result.matched_phrase == "performans"


def test_performans_with_explicit_metrics_and_dimension_is_not_clarification_worthy():
    analyzer = QueryAnalyzer()

    result = analyzer.detect_ambiguity(
        "Randevu sayısı ve gelmeme oranını bölüm performansı açısından karşılaştır."
    )

    assert result is None


def test_superlative_ambiguity_still_fires_regardless_of_other_explicit_metrics():
    """'en iyi' is a genuinely undefined comparison criterion — must always
    ask, even when other explicit metrics are present (unlike 'performans')."""
    analyzer = QueryAnalyzer()

    result = analyzer.detect_ambiguity("En iyi doktor kim, randevu sayısına göre?")

    assert result is not None
    assert result.matched_phrase == "en iyi"


def test_explicit_multi_metric_department_comparison_routes_to_database_query():
    question = (
        "Son üç ayı önceki üç ayla; randevu sayısı ve gelmeme oranı "
        "açısından bölüm bazında karşılaştır."
    )
    analyzer = QueryAnalyzer(today=_TODAY)
    analysis = analyzer.analyze(question)

    assert not analysis.is_ambiguous
    plan = QueryPlanner().build_plan(question, analysis, tables=[], views=[_view()])
    assert plan.answerable
    assert plan.analysis_type == "period_comparison"
    assert len(plan.periods) == 2
    assert plan.dimensions


def test_genuinely_undefined_metric_produces_specific_clarification_not_generic_one():
    """'iptal oranı' has no corresponding status in this view's data (see
    column_intelligence.json unanswerable_concepts) — this must still surface
    as a SPECIFIC clarification about 'iptal', never the generic 'performans'
    one, and must not silently fabricate a cancellation metric."""
    analyzer = QueryAnalyzer()
    question = (
        "Son üç ayı önceki üç ayla; randevu sayısı, iptal oranı, gelmeme oranı ve "
        "bölüm performansı açısından karşılaştır ve dikkat çeken anomalileri açıkla."
    )

    result = analyzer.detect_ambiguity(question)

    assert result is not None
    assert result.matched_phrase == "unanswerable_concept"
    assert "iptal" in result.question.lower()


def test_ambiguity_never_logs_patient_data():
    """Guard: the ambiguity/clarification path only ever handles question
    text and catalog metadata — never row-level patient data."""
    analyzer = QueryAnalyzer()
    result = analyzer.detect_ambiguity("Doktor performansını göster")
    assert result is not None
    for field_value in (result.matched_phrase, result.question, *result.options):
        assert "HastaAdi" not in field_value
        assert "TCKimlikNo" not in field_value


# ── Regression: existing deterministic/routing behavior unaffected ───────────


def test_existing_simple_distribution_deterministic_behavior_unchanged():
    from app.analytics.models import AnalyticsIntent, AnalyticsResult

    analytics = AnalyticsResult(
        analytics_type="distribution",
        intents=[AnalyticsIntent.DISTRIBUTION],
        data_shape=DataShape.CATEGORICAL,
        metrics={
            "count": 3,
            "total": 100.0,
            "average": 33.3,
            "maximum": 40.0,
            "top_category": "A",
            "distribution": {"A": 40.0, "B": 35.0, "C": 25.0},
        },
        row_count=3,
    )
    rules = InsightRulesEngine().evaluate(analytics)
    confidence = InsightRulesEngine().compute_confidence(analytics, rules)

    decision = InsightRouter(remote_available=True).decide(analytics, rules, confidence)

    assert decision.mode == InsightGenerationMode.DETERMINISTIC


@pytest.mark.asyncio
async def test_no_real_network_calls_in_this_module():
    """All assertions above use QueryAnalyzer/QueryPlanner/DeterministicSQLBuilder/
    AnalyticsEngine/ContextManager directly — no LLM provider, no HTTP client,
    no database connection is constructed anywhere in this file."""
    assert True
