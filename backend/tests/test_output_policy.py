from datetime import UTC, datetime

from app.application_models.workflow_models import QueryResult
from app.reporting.output_policy import (
    determine_output_policy,
    determine_requested_response_mode,
    determine_requested_visible_sections,
)


def _result() -> QueryResult:
    return QueryResult(
        columns=["appointment_count"],
        rows=[{"appointment_count": 1}],
        row_count=1,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(UTC),
        database_provider="mssql",
    )


def test_sql_only_question_shows_only_sql_section():
    policy = determine_output_policy(
        question="Sadece SQL sorgusunu ver",
        outcome="EXECUTE_SQL",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "sql"
    assert policy.visible_sections == ["sql"]


def test_sql_only_question_can_be_detected_before_execution():
    assert determine_requested_response_mode("Sadece SQL sorgusunu ver") == "sql"


def test_data_fetch_question_shows_table_section():
    policy = determine_output_policy(
        question="Son 100 randevuyu getir",
        outcome="EXECUTE_SQL",
        generated_sql="SELECT TOP (100) * FROM dbo.vw_RandevuRaporu;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "data"
    assert policy.visible_sections == ["table"]


def test_chart_question_shows_visualization_sections():
    policy = determine_output_policy(
        question="Şubelere göre randevu grafiği çiz",
        outcome="EXECUTE_SQL",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "visualization"
    assert policy.visible_sections == ["chart"]


def test_turkish_chart_suffix_is_detected_from_real_ui_text():
    question = "\u015eubelere g\u00f6re randevu grafi\u011fi \u00e7iz"

    policy = determine_output_policy(
        question=question,
        outcome="EXECUTE_SQL",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )

    assert determine_requested_response_mode(question) == "visualization"
    assert determine_requested_visible_sections(question) == ["chart"]
    assert policy.response_mode == "visualization"
    assert policy.visible_sections == ["chart"]


def test_future_participle_describing_sql_does_not_demote_to_data():
    """'2025 ocak randevularını listeleyecek sql sorgusunu oluşturur musun'
    (real UI bug report, 2026-07-24): 'listeleyecek' describes what the SQL
    will do once run - a relative clause, not a command to run it now. Must
    stay SQL-only, not silently execute and show a table."""
    question = "2025 ocak randevularını listeleyecek sql sorgusunu oluşturur musun"
    assert determine_requested_response_mode(question) == "sql"
    assert determine_requested_visible_sections(question) == ["sql"]

    policy = determine_output_policy(
        question=question,
        outcome="EXECUTE_SQL",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "sql"
    assert policy.visible_sections == ["sql"]


def test_mixed_sql_and_data_question_shows_only_requested_artifacts():
    policy = determine_output_policy(
        question="SQL sorgusunu yaz ve çalıştırıp tabloyu getir",
        outcome="EXECUTE_SQL",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "data"
    assert policy.visible_sections == ["sql", "table"]


def test_mixed_chart_and_table_question_shows_chart_and_table_only():
    policy = determine_output_policy(
        question="subelere gore randevu grafigi ve tabloyu goster",
        outcome="EXECUTE_SQL",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "visualization"
    assert policy.visible_sections == ["table", "chart"]


def test_answer_plus_chart_question_keeps_only_answer_and_chart():
    policy = determine_output_policy(
        question="subelere gore randevu grafigini ciz ve kisaca yorumla",
        outcome="EXECUTE_SQL",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "visualization"
    assert policy.visible_sections == ["answer", "chart"]


def test_requested_visible_sections_can_be_detected_before_execution():
    assert determine_requested_visible_sections("Sadece SQL sorgusunu ver") == ["sql"]
    assert determine_requested_visible_sections("Son 100 randevuyu getir") == ["table"]
    assert determine_requested_visible_sections("Grafik çiz") == ["chart"]


def test_terminal_outcome_stays_answer_only():
    policy = determine_output_policy(
        question="Sonuçları getir",
        outcome="NO_RESULT_GUIDANCE",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "answer"
    assert policy.visible_sections == ["answer"]
