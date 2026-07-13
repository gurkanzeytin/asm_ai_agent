"""Regression tests for NLU-001 — Natural Language Understanding v2.

Covers medical terminology rewrites, conversational-language normalization,
relative dates, ranking/aggregation phrase detection, query expansion,
ambiguity detection, and the agent-graph clarification routing.
"""

from datetime import date

import pytest

from app.agent.graph import route_by_intent
from app.agent.nodes.generate_clarification import GenerateClarificationNode
from app.agent.state import AgentState
from app.application_models.intent import IntentResult, IntentType
from app.application_models.query_analysis import AmbiguityResult
from app.services.query_analyzer import QueryAnalyzer

TODAY = date(2026, 7, 13)  # a Monday


@pytest.fixture
def analyzer() -> QueryAnalyzer:
    return QueryAnalyzer(today=TODAY)


# ── Part 1: Medical terminology ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "expected_fragment", "expected_synonym"),
    [
        ("Dahiliye doktorları", "ic hastaliklari doktorları", "dahiliye -> iç hastalıkları"),
        ("Cildiye randevuları", "dermatoloji randevuları", "cildiye -> dermatoloji"),
        ("Göz doktorları", "goz hastaliklari doktorları", "göz -> göz hastalıkları"),
        (
            "Ortopedi bölümü",
            "ortopedi ve travmatoloji bölümü",
            "ortopedi -> ortopedi ve travmatoloji",
        ),
        ("KBB bölümü", "kulak burun bogaz bölümü", "kbb -> kulak burun bogaz"),
    ],
)
def test_medical_terminology_rewrites(analyzer, query, expected_fragment, expected_synonym):
    analysis = analyzer.analyze(query)

    assert analysis.normalized_query == expected_fragment
    assert expected_synonym in analysis.matched_synonyms


def test_ortopedi_rewrite_is_idempotent(analyzer):
    analysis = analyzer.analyze("Ortopedi ve travmatoloji doktorları")

    assert analysis.normalized_query.count("travmatoloji") == 1


def test_goz_without_department_context_not_rewritten(analyzer):
    analysis = analyzer.analyze("Göz rengi mavi olan hastalar")

    assert "hastaliklari" not in analysis.normalized_query


# ── Part 2: Relative time understanding ───────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "expected_start", "expected_end", "granularity"),
    [
        ("Bugün kaç randevu var", TODAY, TODAY, "day"),
        ("Dün kaç randevu vardı", date(2026, 7, 12), date(2026, 7, 12), "day"),
        ("Yarın randevusu olan hastalar", date(2026, 7, 14), date(2026, 7, 14), "day"),
        ("Bu hafta randevusu olan doktorlar", date(2026, 7, 13), date(2026, 7, 19), "week"),
        ("Geçen hafta yapılan randevular", date(2026, 7, 6), date(2026, 7, 12), "week"),
        ("Bu ay kaç hasta geldi", date(2026, 7, 1), date(2026, 7, 31), "month"),
        ("Geçen ay kaç hasta geldi", date(2026, 6, 1), date(2026, 6, 30), "month"),
        ("Son 7 gün randevuları", date(2026, 7, 7), TODAY, "day"),
        ("Son 30 gün randevuları", date(2026, 6, 14), TODAY, "day"),
        ("Son 3 ay randevu sayısı", date(2026, 4, 13), TODAY, "month"),
        ("Son 6 ay randevu sayısı", date(2026, 1, 13), TODAY, "month"),
        ("Son 1 yıl içindeki randevular", date(2025, 7, 13), TODAY, "year"),
    ],
)
def test_relative_time_detection(analyzer, query, expected_start, expected_end, granularity):
    analysis = analyzer.analyze(query)

    assert analysis.detected_dates, f"no dates detected for: {query}"
    detected = analysis.detected_dates[0]
    assert detected.start_date == expected_start
    assert detected.end_date == expected_end
    assert detected.granularity == granularity


def test_final_query_resolves_single_day_expression(analyzer):
    analysis = analyzer.analyze("Bugün kaç randevu oluşturuldu?")

    assert "2026-07-13 tarihinde" in analysis.final_query
    assert "bugün" not in analysis.final_query


def test_final_query_resolves_range_expression(analyzer):
    analysis = analyzer.analyze("Geçen ay kaç hasta geldi?")

    assert "2026-06-01 ile 2026-06-30 tarihleri arasinda" in analysis.final_query
    assert "geçen ay" not in analysis.final_query


def test_normalized_query_keeps_natural_language_for_retrieval(analyzer):
    analysis = analyzer.analyze("Geçen ay kaç hasta geldi?")

    assert "geçen ay" in analysis.normalized_query


# ── Part 3: Conversational language ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Lütfen doktorları listele", "doktorları listele"),
        ("Bana randevuları göster", "randevuları göster"),
        ("Acaba kaç hasta var", "kaç hasta var"),
        ("Doktorları görebilir miyim", "doktorları goster"),
        ("Randevu sayısını söyler misin", "randevu sayısını"),
        ("Doktor listesine bakabilir misin", "doktor listesine goster"),
    ],
)
def test_conversational_fillers_normalized(analyzer, query, expected):
    analysis = analyzer.analyze(query)

    assert analysis.normalized_query == expected


# ── Part 1/4: Actions, aggregates, ranking ────────────────────────────────────


@pytest.mark.parametrize(
    ("query", "expected_operation"),
    [
        ("Doktorları göster", "LIST"),
        ("Hekimleri listele", "LIST"),
        ("Randevuları getir", "LIST"),
        ("Hastaları bul", "LIST"),
        ("Doktorları görebilir miyim", "LIST"),
        ("Bugün kaç randevu oluşturuldu", "COUNT"),
        ("Toplam fatura tutarı nedir", "SUM"),
        ("Ortalama randevu süresi", "AVG"),
    ],
)
def test_operation_detection(analyzer, query, expected_operation):
    analysis = analyzer.analyze(query)

    assert expected_operation in analysis.detected_operations


def test_limit_detection_ilk_5(analyzer):
    analysis = analyzer.analyze("İlk 5 doktoru göster")

    assert analysis.detected_limit == 5
    assert analysis.detected_order is None


def test_limit_detection_son_5_is_order_desc(analyzer):
    analysis = analyzer.analyze("Son 5 randevuyu göster")

    assert analysis.detected_limit == 5
    assert analysis.detected_order == "DESC"


def test_son_7_gun_is_temporal_not_limit(analyzer):
    analysis = analyzer.analyze("Son 7 gün randevuları")

    assert analysis.detected_limit is None
    assert analysis.detected_dates


@pytest.mark.parametrize(
    ("query", "expected_fragment"),
    [
        ("En yoğun bölüm hangisi?", "en fazla randevusu olan bölüm hangisi"),
        ("En boş doktor kim?", "en az randevusu olan doktor kim"),
        ("En çok çalışan doktor", "en fazla islem yapan doktor"),
        ("En az çalışan doktor", "en az islem yapan doktor"),
        ("Geçen ay en çok hasta bakan doktor kim?", "en fazla hastasi olan doktor kim"),
    ],
)
def test_ranking_and_expansion_rewrites(analyzer, query, expected_fragment):
    analysis = analyzer.analyze(query)

    assert expected_fragment in analysis.normalized_query


def test_success_criteria_composite_query(analyzer):
    analysis = analyzer.analyze("Kalp doktorlarından bugün en yoğun olan ilk 5 kişiyi göster.")

    assert "kardiyoloji" in analysis.normalized_query
    assert "en fazla randevusu olan" in analysis.normalized_query
    assert analysis.detected_limit == 5
    assert "LIST" in analysis.detected_operations
    assert "2026-07-13 tarihinde" in analysis.final_query
    assert not analysis.is_ambiguous


# ── Part 5: Ambiguity detection ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "En başarılı doktor kim?",
        "En iyi doktor hangisi?",
        "En kötü doktor kim?",
        "En verimli doktor kim?",
    ],
)
def test_ambiguous_queries_detected(analyzer, query):
    analysis = analyzer.analyze(query)

    assert analysis.is_ambiguous
    assert analysis.ambiguity is not None
    assert analysis.ambiguity.question
    assert "Randevu sayısı" in analysis.ambiguity.options


@pytest.mark.parametrize(
    "query",
    [
        "En yoğun doktor kim?",
        "En fazla randevusu olan doktor",
        "Doktorları listele",
    ],
)
def test_deterministic_queries_not_ambiguous(analyzer, query):
    analysis = analyzer.analyze(query)

    assert not analysis.is_ambiguous


def test_detect_ambiguity_public_helper(analyzer):
    result = analyzer.detect_ambiguity("En başarılı doktor kim?")

    assert result is not None
    assert result.matched_phrase == "en basarili"


# ── Graph routing & clarification response ────────────────────────────────────


def _db_intent() -> IntentResult:
    return IntentResult(
        intent=IntentType.DATABASE_QUERY,
        confidence=0.9,
        reason="test",
        matched_keywords=["doktor"],
        metadata={},
    )


def test_route_by_intent_diverts_ambiguous_database_query():
    state = AgentState(
        question="En iyi doktor kim?",
        intent=_db_intent(),
        ambiguity=AmbiguityResult(matched_phrase="en iyi", question="Kriter?", options=["A"]),
    )

    assert route_by_intent(state) == "unknown"


def test_route_by_intent_keeps_unambiguous_database_query():
    state = AgentState(question="Doktorları listele", intent=_db_intent())

    assert route_by_intent(state) == "database_query"


def test_route_by_intent_does_not_divert_non_database_intents():
    state = AgentState(
        question="merhaba",
        intent=IntentResult(
            intent=IntentType.GENERAL_CHAT,
            confidence=1.0,
            reason="test",
            matched_keywords=["merhaba"],
            metadata={},
        ),
        ambiguity=None,
    )

    assert route_by_intent(state) == "general_chat"


@pytest.mark.asyncio
async def test_clarification_node_renders_ambiguity_options():
    state = AgentState(
        question="En başarılı doktor kim?",
        ambiguity=AmbiguityResult(
            matched_phrase="en basarili",
            question="Başarı kriteri olarak neyi kullanmamı istersiniz?",
            options=["Randevu sayısı", "Hasta sayısı", "Reçete sayısı", "Başka bir kriter"],
        ),
    )

    result = await GenerateClarificationNode().execute(state)

    report = result.generated_report
    assert report is not None
    assert "Başarı kriteri olarak neyi kullanmamı istersiniz?" in report.markdown
    assert "• Randevu sayısı" in report.markdown
    assert "• Başka bir kriter" in report.markdown


@pytest.mark.asyncio
async def test_clarification_node_falls_back_to_generic_message():
    state = AgentState(question="asdf qwer")

    result = await GenerateClarificationNode().execute(state)

    assert "rephrase" in result.generated_report.markdown


@pytest.mark.asyncio
async def test_analyze_intent_node_sets_ambiguity():
    from app.agent.nodes.analyze_intent import AnalyzeIntentNode
    from app.services.intent_classifier import IntentClassifier

    node = AnalyzeIntentNode(IntentClassifier(), query_analyzer=QueryAnalyzer(today=TODAY))
    state = AgentState(question="En iyi doktor kim?")

    result = await node.execute(state)

    assert result.ambiguity is not None
    assert result.ambiguity.matched_phrase == "en iyi"


# ── Turkish suffix handling & normalization ───────────────────────────────────


def test_suffix_harmonization_still_applies(analyzer):
    analysis = analyzer.analyze("Hekimlerin listesi")

    assert analysis.normalized_query.startswith("doktorların")


def test_diacritics_insensitive_matching(analyzer):
    analysis = analyzer.analyze("en yogun bolum")

    assert "en fazla randevusu olan bolum" in analysis.normalized_query


def test_pipeline_stages_are_populated(analyzer):
    analysis = analyzer.analyze("Lütfen bugün en çok hasta bakan doktoru göster")

    assert analysis.rewritten_query  # post-rewrite stage
    assert analysis.expanded_query  # post-expansion stage
    assert analysis.final_query  # dates resolved
    assert "hasta bakan" in analysis.rewritten_query
    assert "en fazla hastasi olan" in analysis.expanded_query
    assert "2026-07-13 tarihinde" in analysis.final_query
