from datetime import date

import pytest

from app.context.extractor import ContextExtractor
from app.database_intelligence.models import ViewMetadata
from app.planning.planner import QueryPlanner
from app.semantics import catalog
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.services.query_analyzer import QueryAnalyzer

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


@pytest.mark.parametrize(
    "question",
    [
        "2024te kac randevu var",
        "2024'te kac randevu var",
        "2024 ten kac randevu var",
    ],
)
def test_year_case_suffixes_resolve_to_the_same_calendar_year(question):
    analyzer = QueryAnalyzer(today=date(2026, 8, 2))

    analysis = analyzer.analyze(question)

    assert len(analysis.detected_dates) == 1
    assert analysis.detected_dates[0].start_date == date(2024, 1, 1)
    assert analysis.detected_dates[0].end_date == date(2024, 12, 31)
    assert ContextExtractor().extract(question).date_expression is not None


def test_year_like_aggregate_threshold_is_not_reinterpreted_as_a_date():
    analysis = QueryAnalyzer(today=date(2026, 8, 2)).analyze(
        "2024ten fazla randevusu olan bolumler"
    )

    assert analysis.detected_dates == []


@pytest.mark.parametrize(
    "question",
    [
        "gecen sene kac randevu vardi",
        "onceki sene kac randevu vardi",
    ],
)
def test_colloquial_year_words_resolve_to_previous_calendar_year(question):
    analysis = QueryAnalyzer(today=date(2026, 8, 2)).analyze(question)

    assert len(analysis.detected_dates) == 1
    assert analysis.detected_dates[0].start_date == date(2025, 1, 1)
    assert analysis.detected_dates[0].end_date == date(2025, 12, 31)


def test_year_range_with_later_difference_word_resolves_as_two_periods():
    analysis = QueryAnalyzer(today=date(2026, 8, 2)).analyze(
        "2025 ile 2024 arasi randevu adedi farki ne"
    )

    assert [(item.start_date.year, item.end_date.year) for item in analysis.detected_dates] == [
        (2025, 2025),
        (2024, 2024),
    ]


@pytest.mark.parametrize(
    ("question", "normalized_fragment"),
    [
        ("ortalama randv suresi", "ortalama randevu suresi"),
        ("randvulari say", "randevulari say"),
        ("randavu sayisi", "randevu sayisi"),
        ("girsi yapilmislar", "giris yapilmislar"),
        ("bekliyo olanlar", "bekliyor olanlar"),
    ],
)
def test_appointment_spelling_variants_normalize_without_full_question_rules(
    question, normalized_fragment
):
    analysis = QueryAnalyzer().analyze(question)

    assert ContextExtractor().fold(normalized_fragment) in ContextExtractor().fold(
        analysis.expanded_query
    )


def test_normalized_appointment_word_reaches_catalog_metric_and_safe_sql():
    question = "2024te ortalama randv suresi kacti ya"
    analyzer = QueryAnalyzer(today=date(2026, 8, 2))
    analysis = analyzer.analyze(question)
    plan = QueryPlanner().build_plan(
        question,
        analysis,
        tables=[],
        views=[VIEW],
    )
    built = DeterministicSQLBuilder().build(plan)

    assert plan.analysis_type == "duration_analysis"
    assert plan.metrics == ["appointment_duration_average"]
    assert set(plan.required_columns) >= {"RandevuSuresi"}
    assert isinstance(built, DeterministicSQL)
    assert "AVG(CAST(RandevuSuresi AS FLOAT))" in built.sql
    assert "2024-01-01" in built.sql and "2024-12-31" in built.sql


@pytest.mark.parametrize(
    ("question", "expected_metric"),
    [
        ("hekim hanesi atanmayan randevular", "missing_doctor_count"),
        ("klinik bilgisi null birakilan satirlar", "missing_department_count"),
        ("bitis zamani baslama zamanindan erken", "invalid_date_range_count"),
        ("dakikasi 0dan kucuk veya esit", "zero_or_negative_duration_count"),
        ("iki tarih arasi dakika celisen", "duration_mismatch_count"),
        ("check in edilenlerin butune orani", "checked_in_rate"),
        ("halen islemde gorunenlerin adedi", "in_progress_count"),
        ("kuyrukta duranlar yuzde kac", "waiting_rate"),
        ("bir kisi ort kac kere randevu almis", "appointments_per_patient"),
        ("gununde kaydedilen randevu adedi", "same_day_booking_count"),
        ("protokol randevudan sonra ne zaman aciliyo", "protocol_opening_delay_average"),
        ("takvim suresi gercek sureye gore kac dakika sapma", "duration_difference"),
        ("fiili randevu ort ne kadar surmus", "actual_duration_from_dates"),
        ("randevularin aylik trendi", "monthly_appointment_count"),
        ("gunde ort randevu", "daily_average_appointment_count"),
        ("iki kere randevu alan kisi sayisi", "repeat_patient_count"),
        ("tek gunde farkli hekim goren kisi sayisi", "same_day_multi_doctor_patient_count"),
        ("kayit tarihiyle randevu tarihi ayni gun olanlar", "same_day_booking_count"),
        ("randevudan sonra acilmis protokollerin ort gecikmesi", "protocol_opening_delay_average"),
        ("baslangic bitise gore gercek dakika ortalamasi", "actual_duration_from_dates"),
        ("takvim gunu basina ort randevu", "daily_average_appointment_count"),
        ("bir gun icinde degisik hekim goren hasta sayisi", "same_day_multi_doctor_patient_count"),
        (
            "ayni takvim tarihinde birden cok hekim goren kisi gun sayisi",
            "same_day_multi_doctor_patient_count",
        ),
        ("bekleme kuyrugundakilerin toplam icindeki hissesi", "waiting_rate"),
    ],
)
def test_compositional_metric_matching_uses_concept_and_operator_groups(
    question, expected_metric
):
    folded = ContextExtractor().fold(question)

    assert expected_metric in catalog.match_compositional_metrics(folded)


@pytest.mark.parametrize(
    "question",
    [
        "doktor bazinda randevu sayisi",
        "klinik dagilimi",
        "ortalama randevu suresi",
        "baslangic tarihine gore randevular",
        "kuyruk yogunlugu",
    ],
)
def test_compositional_metric_matching_requires_every_signal_group(question):
    assert catalog.match_compositional_metrics(ContextExtractor().fold(question)) == []


def test_more_specific_compositional_duration_metric_suppresses_generic_duration():
    folded = ContextExtractor().fold(
        "takvimdeki sureyle gercek sure arasinda kac dakika oynuyor"
    )

    assert catalog.match_compositional_metrics(folded) == ["duration_difference"]


def test_specialized_relationship_metric_outranks_generic_compositional_metric():
    question = "farkli subelerde tekrar eden hasta sayisi nedir"
    plan = QueryPlanner().build_plan(
        question,
        QueryAnalyzer().analyze(question),
        tables=[],
        views=[VIEW],
    )

    assert plan.metrics == ["cross_branch_repeat_patient_count"]
    assert set(plan.required_columns) >= {"HastaId", "SubeAdi", "Id"}


def test_compositional_relationship_suppresses_multiple_broad_keyword_metrics():
    question = "tek gunde farkli doktorlara giden benzersiz hasta adedi"
    plan = QueryPlanner().build_plan(
        question,
        QueryAnalyzer().analyze(question),
        tables=[],
        views=[VIEW],
    )

    assert plan.metrics == ["same_day_multi_doctor_patient_count"]
    assert plan.dimensions == []
    assert set(plan.required_columns) >= {"HastaId", "BaslangicTarihi", "DoktorId"}


def test_compositional_metric_does_not_replace_explicit_multi_metric_request():
    question = "2025 randevu sayisi ile tekil hasta sayisini birlikte goster"
    plan = QueryPlanner().build_plan(
        question,
        QueryAnalyzer().analyze(question),
        tables=[],
        views=[VIEW],
    )

    assert plan.metrics == ["appointment_count", "unique_patient_count"]


def test_compositional_metric_keeps_directly_matched_sibling_metric():
    question = "Bolum bazinda planlanan sure ile fiili sure farki nedir"
    plan = QueryPlanner().build_plan(
        question,
        QueryAnalyzer().analyze(question),
        tables=[],
        views=[VIEW],
    )

    assert plan.metrics == ["actual_duration_from_dates", "duration_difference"]


@pytest.mark.parametrize(
    "question",
    [
        "gelmeme oranina gore sirala",
        "gerceklesme oranina gore sirala",
    ],
)
def test_sorting_word_is_not_reinterpreted_as_waiting_status(question):
    folded = ContextExtractor().fold(question)

    assert "waiting_rate" not in catalog.match_compositional_metrics(folded)
