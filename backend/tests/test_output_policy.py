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


def test_verir_misin_phrasing_is_sql_not_data():
    """'Bu sorgunun SQL'ini verir misin?' (polite '(will you) give me the
    SQL?') was demoted from 'sql' to 'data' mode - the VERB 'verir'
    (conjugated form of 'vermek', to give) false-positive-matched the DATA
    marker's 'veri\\w*' (the NOUN 'veri', data), since 'verir' = 'veri' + 'r'
    is a literal prefix match. Silently triggered an unrelated 'which data
    do you mean?' clarification instead of returning the SQL
    (2026-07-24 real UI bug report)."""
    assert determine_requested_response_mode("Bu sorgunun SQL'ini verir misin?") == "sql"
    assert determine_requested_response_mode("Sorgusunu verir misin?") == "sql"


def test_veri_noun_forms_still_read_as_data_request():
    """Regression guard: excluding the 'verir' verb form must not affect
    genuine noun inflections of 'veri' (data)."""
    assert determine_requested_response_mode("Verileri göster") == "data"
    assert determine_requested_response_mode("Verilerini getir") == "data"


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


def test_negated_calistir_does_not_flip_sql_only_to_data():
    """'Bunu SQL olarak yazacak sorguyu ver, çalıştırma' ('give me the query,
    don't run it') has 'çalıştırma' - the Turkish negation suffix '-ma'
    attaches directly to the verb stem, so a bare \\w* wildcard on
    'calistir\\w*' can't distinguish it from 'çalıştır' (run, positive). The
    EXECUTION marker matched anyway and silently overrode the explicit
    SQL-only request, executing and returning 'data' mode for a question
    that explicitly asked NOT to run it (2026-07-24, live multi-turn
    testing). SQL_ONLY_MARKER already special-cases bare 'calistirma' as an
    SQL-only signal - the EXECUTION marker must not contradict it."""
    question = "Bunu SQL olarak yazacak sorguyu ver, çalıştırma"
    assert determine_requested_response_mode(question) == "sql"
    assert determine_requested_visible_sections(question) == ["sql"]


def test_positive_calistir_forms_still_read_as_execution():
    """Regression guard: excluding the negated '-ma' form must not affect
    genuine positive conjugations of 'çalıştır' (run)."""
    assert determine_requested_response_mode("Bu SQL sorgusunu çalıştır") == "data"
    assert determine_requested_response_mode("Sorguyu çalıştırır mısın?") == "data"


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
