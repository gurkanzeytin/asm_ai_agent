from datetime import UTC, datetime

import pytest

from app.application_models.workflow_models import QueryResult
from app.reporting.output_policy import (
    detect_requested_visualization,
    determine_output_policy,
    determine_requested_response_mode,
    determine_requested_visible_sections,
    should_render_expanded_answer,
)


def test_detect_requested_visualization_maps_specific_chart_words():
    assert detect_requested_visualization("bunu pasta grafik olarak goster") == "PIE_CHART"
    assert detect_requested_visualization("cizgi grafik olarak goster") == "LINE_CHART"
    assert detect_requested_visualization("sutun grafik yap") == "BAR_CHART"


def test_detect_requested_visualization_none_when_absent_or_negated():
    assert detect_requested_visualization("bolum bazinda randevu sayisi") is None
    # Negation must not force a pie ("pasta grafik değil, tablo ver").
    assert detect_requested_visualization("pasta grafik degil tablo ver") is None


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


def test_negated_grafik_request_shows_only_table_not_chart():
    """'Bunu grafik değil sadece tablo olarak ver' (NOT a chart, just table)
    following an earlier chart request came back with BOTH a fully expanded
    chart section AND the requested table - the bare 'grafik\\w*' substring
    marker has no way to tell a positive chart request apart from its own
    explicit rejection a few tokens later via 'değil' (2026-07-27, live UI
    testing)."""
    question = "Bunu grafik değil sadece tablo olarak ver"
    assert determine_requested_response_mode(question) == "data"
    assert determine_requested_visible_sections(question) == ["table"]

    policy = determine_output_policy(
        question=question,
        outcome="EXECUTE_SQL",
        generated_sql="SELECT 1;",
        query_result=_result(),
        analytics=None,
    )
    assert policy.response_mode == "data"
    assert policy.visible_sections == ["table"]


@pytest.mark.parametrize(
    "question",
    [
        "Sadece tablo göster, grafik olmasın",
        "Grafik istemiyorum, tabloyu ver",
        "Tablo ver, grafik gerekmiyor",
    ],
)
def test_non_degil_chart_rejections_also_suppress_the_chart(question):
    """The rejection is not always "değil" — "grafik olmasın"/"istemiyorum"
    reject just as explicitly but still rendered the chart panel next to the
    requested table (Codex live UI testing, 2026-07-31)."""
    assert determine_requested_response_mode(question) == "data"
    assert determine_requested_visible_sections(question) == ["table"]


def test_positive_grafik_forms_still_read_as_visualization():
    """Regression guard: excluding 'grafik ... değil' must not affect a
    genuine positive chart request, including one with filler words between
    the noun and a later, unrelated 'değil'."""
    assert determine_requested_response_mode("Şubelere göre randevu grafiği çiz") == (
        "visualization"
    )
    assert determine_requested_visible_sections("Grafik olarak göster, tablo değil") == [
        "chart"
    ]


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


def test_expanded_answer_requires_explicit_detail_request():
    assert should_render_expanded_answer("Kısaca yorumla") is False
    assert should_render_expanded_answer("Ortalama değer kaç?") is False
    assert should_render_expanded_answer("Detaylı rapor ver") is True
    assert should_render_expanded_answer("Sorgulanan metrikleri ve bulguları göster") is True


@pytest.mark.parametrize(
    "question",
    [
        "Bu son sorgunun SQL'ini çalıştırmadan göster.",
        "SQL sorgusunu ver, çalıştırmayın.",
    ],
)
def test_suffixed_negative_calistirma_is_sql_only(question):
    """"çalıştırmaDAN" (without running) matched the execution marker, so a
    question that explicitly said not to run it came back executed with the
    table alongside the SQL (live UI testing, 2026-07-31)."""
    assert determine_requested_response_mode(question) == "sql"
    assert determine_requested_visible_sections(question) == ["sql"]


def test_positive_calistirmak_infinitive_still_executes():
    """Guard: "çalıştırmak" (to run) is positive and must stay an execution."""
    assert determine_requested_response_mode("Bu sorguyu çalıştırmak istiyorum") == "data"


@pytest.mark.parametrize(
    "question",
    [
        "Grafiği kaldır, tablo ve kısa yorum ver",
        "Pasta grafik yapma, tabloyu ver",
        "Grafiği sil, tablo göster",
    ],
)
def test_chart_removal_verbs_suppress_the_chart(question):
    """"kaldır"/"sil" REMOVE an already-rendered chart and "yapma" is the
    negative imperative — all three left the chart on screen (live UI testing,
    2026-08-01)."""
    assert "chart" not in determine_requested_visible_sections(question)


def test_positive_yapmak_infinitive_still_requests_a_chart():
    """Guard: "grafik yapmak istiyorum" is positive and must stay a chart."""
    assert determine_requested_response_mode("Grafik yapmak istiyorum") == "visualization"


@pytest.mark.parametrize(
    "question",
    [
        "Bunu yönetici özeti olarak ver",
        "Kısa yorumu ver",
        "Bunu özetle",
        "Sonucu değerlendirir misin",
    ],
)
def test_suffixed_answer_markers_are_detected(question):
    """The stems were anchored, so the most management-facing phrasing of all —
    "yönetici özeti" — carried no answer signal (live UI testing, 2026-08-01)."""
    assert "answer" in determine_requested_visible_sections(question)
