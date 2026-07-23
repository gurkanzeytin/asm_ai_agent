"""ASM domain semantic training pack.

These tests lock common Turkish appointment-reporting phrases to the verified
dbo.vw_RandevuRaporu view semantics. They are deterministic: no LLM, no DB.
"""

import pytest

from app.database_intelligence.models import ViewMetadata
from app.planning.compliance import PlanComplianceValidator
from app.planning.planner import QueryPlanner
from app.semantics import catalog
from app.services.deterministic_sql_builder import DeterministicSQLBuilder
from app.services.query_analyzer import QueryAnalyzer

VIEW_NAME = "dbo.vw_RandevuRaporu"
VIEW = ViewMetadata(name=VIEW_NAME, columns=[])

EXPECTED_RANDEVU_RAPORU_COLUMNS = {
    "Id",
    "BaslangicTarihi",
    "BitisTarihi",
    "RandevuSuresi",
    "RandevuDurumu",
    "HastaId",
    "RandevuTipiAdi",
    "RandevuyuVeren",
    "HastaAdi",
    "HastaSoyadi",
    "DogumTarihi",
    "CinsiyetId",
    "HastaId2",
    "Uyruk",
    "BolumId",
    "DoktorId",
    "HizmetAdi",
    "ProtokolIslemState",
    "KategoriAdi",
    "GenelRandevuKaynakAdi",
    "GenelRandevuBolumAdi",
    "ProtokolAcilisTarihi",
    "SubeAdi",
    "CreatedDate",
}


def plan_for(question: str):
    analysis = QueryAnalyzer().analyze(question)
    return QueryPlanner().build_plan(question, analysis, tables=[], views=[VIEW])


def sql_for(question: str) -> str:
    plan = plan_for(question)
    built = DeterministicSQLBuilder().build(plan)
    assert hasattr(built, "sql"), getattr(built, "reason", "")
    return built.sql


def date_columns(plan) -> set[str]:
    return {date_filter.column for date_filter in plan.date_filters}


def test_randevu_raporu_column_dictionary_covers_all_24_columns():
    column_catalog = catalog.load_column_catalog()

    assert column_catalog.view == VIEW_NAME
    assert column_catalog.column_names() == EXPECTED_RANDEVU_RAPORU_COLUMNS
    assert len(column_catalog.columns) == 24

    for spec in column_catalog.columns:
        assert spec.business_name
        assert spec.description
        assert spec.data_role
        assert spec.semantic_type
        assert spec.synonyms, spec.column
        assert spec.supported_operations, spec.column


def test_today_appointment_count_uses_appointment_date_and_count():
    plan = plan_for("bugunku randevularin adedini soyle")

    assert plan.metrics == ["appointment_count"]
    assert date_columns(plan) == {"BaslangicTarihi"}

    sql = sql_for("bugunku randevularin adedini soyle")
    assert "COUNT(*) AS appointment_count" in sql
    assert "BaslangicTarihi >= '2026-07-23'" in sql
    assert "CreatedDate" not in sql


def test_created_today_appointment_count_uses_created_date():
    plan = plan_for("bugun olusturulan randevu sayisi kac")

    assert plan.metrics == ["appointment_count"]
    assert date_columns(plan) == {"CreatedDate"}

    sql = sql_for("bugun olusturulan randevu sayisi kac")
    assert "CreatedDate >= '2026-07-23'" in sql
    assert "BaslangicTarihi >=" not in sql


@pytest.mark.parametrize(
    ("question", "dimension", "excluded"),
    [
        (
            "doktorlara gore randevu dagilimini getir",
            "GenelRandevuKaynakAdi",
            {"RandevuyuVeren", "HastaAdi"},
        ),
        (
            "hekimlere gore gelmeme orani",
            "GenelRandevuKaynakAdi",
            {"RandevuyuVeren", "HastaAdi"},
        ),
        (
            "randevu kaynaklarina gore randevu sayisi",
            "GenelRandevuKaynakAdi",
            {"RandevuyuVeren", "HastaAdi"},
        ),
        (
            "randevuyu verenlere gore randevu sayisi",
            "RandevuyuVeren",
            {"GenelRandevuKaynakAdi"},
        ),
        (
            "randevuyu verenlerin dagilimi",
            "RandevuyuVeren",
            {"GenelRandevuKaynakAdi"},
        ),
        (
            "branslara gore randevu sayisi",
            "GenelRandevuBolumAdi",
            {"SubeAdi", "KategoriAdi"},
        ),
        (
            "subelere gore randevu sayisi",
            "SubeAdi",
            {"GenelRandevuBolumAdi"},
        ),
        (
            "lokasyonlara gore randevu dagilimi",
            "SubeAdi",
            {"GenelRandevuBolumAdi"},
        ),
        (
            "kategoriye gore randevu dagilimi",
            "KategoriAdi",
            {"GenelRandevuBolumAdi"},
        ),
    ],
)
def test_business_dimensions_map_to_verified_view_columns(question, dimension, excluded):
    plan = plan_for(question)

    assert plan.metrics
    assert plan.dimensions == [dimension]
    assert plan.projection == [dimension]
    assert not (set(plan.projection) & excluded)

    sql = sql_for(question)
    assert f"GROUP BY {dimension}" in sql
    assert "COUNT(*) AS" in sql or "NULLIF(COUNT(*), 0)" in sql
    assert PlanComplianceValidator().check(sql, plan, deterministic=True).compliant


@pytest.mark.parametrize(
    ("question", "metric", "status_value"),
    [
        ("bekleyenleri say", "waiting_count", "Beklemede"),
        ("gelmeyenleri say", "no_show_count", "Gelmedi"),
        ("gerceklesenleri say", "completed_appointment_count", "Gerçekleşti"),
        ("giris yapilmislarin orani", "checked_in_rate", "Giriş Yapılmış"),
        ("islem surmekte olan randevulari say", "in_progress_count", "İşlem Sürmekte"),
    ],
)
def test_status_phrases_select_specific_status_metrics(question, metric, status_value):
    plan = plan_for(question)

    assert plan.metrics == [metric]
    sql = sql_for(question)
    assert f"AS {metric}" in sql
    assert f"N'{status_value}'" in sql
    assert "COUNT(*) AS appointment_count" not in sql


def test_no_show_rate_by_branch_uses_department_dimension():
    plan = plan_for("gelmeme oranini branslara gore goster")

    assert plan.metrics == ["no_show_rate"]
    assert plan.dimensions == ["GenelRandevuBolumAdi"]

    sql = sql_for("gelmeme oranini branslara gore goster")
    assert "AS no_show_rate" in sql
    assert "GROUP BY GenelRandevuBolumAdi" in sql
    assert "NULLIF(COUNT(*), 0)" in sql


def test_removed_phone_field_is_not_turned_into_generic_appointment_list():
    plan = plan_for("hasta telefonlarini goster")

    assert plan.answerable is False
    assert plan.answerability_reason
    assert plan.metrics == []
    assert plan.projection == []

    built = DeterministicSQLBuilder().build(plan)
    assert not hasattr(built, "sql")


@pytest.mark.parametrize(
    ("question", "status_value"),
    [
        ("son 20 gelmeyen randevuyu getir", "Gelmedi"),
        ("son 20 bekleyen randevuyu getir", "Beklemede"),
    ],
)
def test_status_filtered_last_n_requests_stay_raw_lists(question, status_value):
    plan = plan_for(question)

    assert plan.analysis_type == "list"
    assert plan.limit == 20
    assert plan.metrics == []

    sql = sql_for(question)
    assert "SELECT TOP (20) Id, BaslangicTarihi" in sql
    assert f"WHERE RandevuDurumu = N'{status_value}'" in sql
    assert "COUNT(" not in sql.upper()


def test_created_today_last_n_list_uses_created_date_for_filter_and_order():
    plan = plan_for("bugun olusturulan son 20 randevuyu getir")

    assert plan.analysis_type == "list"
    assert plan.limit == 20
    assert date_columns(plan) == {"CreatedDate"}

    sql = sql_for("bugun olusturulan son 20 randevuyu getir")
    assert "WHERE CreatedDate >= '2026-07-23'" in sql
    assert "ORDER BY CreatedDate DESC" in sql
    assert "COUNT(" not in sql.upper()


def test_real_turkish_created_today_last_n_uses_created_date():
    question = "Bug\u00fcn olu\u015fturulan son 20 randevuyu getir"
    plan = plan_for(question)

    assert plan.analysis_type == "list"
    assert plan.limit == 20
    assert date_columns(plan) == {"CreatedDate"}


def test_real_turkish_branch_chart_groups_by_branch_column():
    question = "\u015eubelere g\u00f6re randevu grafi\u011fi \u00e7iz"
    plan = plan_for(question)

    assert plan.metrics in (["appointment_count"], ["appointments_per_branch"])
    assert plan.dimensions == ["SubeAdi"]
    assert plan.projection == ["SubeAdi"]

    sql = sql_for(question)
    assert "GROUP BY SubeAdi" in sql
    assert "COUNT(*) AS" in sql


@pytest.mark.parametrize(
    ("question", "dimension"),
    [
        ("cinsiyete gore randevu sayisi", "CinsiyetId"),
        ("uyruga gore randevu dagilimi", "Uyruk"),
        ("dogum tarihine gore hasta dagilimi", "DogumTarihi"),
    ],
)
def test_demographic_dimensions_use_existing_view_columns(question, dimension):
    plan = plan_for(question)

    assert dimension in plan.dimensions
    sql = sql_for(question)
    assert f"GROUP BY {dimension}" in sql
    assert "HastaAdi" not in sql
    assert "HastaSoyadi" not in sql


@pytest.mark.parametrize(
    ("question", "metrics", "dimensions", "analysis_type"),
    [
        ("cinsiyete gore randevu sayisi", ["appointment_count"], ["CinsiyetId"], "count"),
        ("uyruga gore randevu dagilimi", ["appointment_count"], ["Uyruk"], "distribution"),
        (
            "randevu tipine gore dagilim",
            ["appointments_per_type"],
            ["RandevuTipiAdi"],
            "distribution",
        ),
        ("hizmete gore randevu sayisi", ["appointment_count"], ["HizmetAdi"], "count"),
        ("kategoriye gore randevu sayisi", ["appointment_count"], ["KategoriAdi"], "count"),
        (
            "randevu durumuna gore dagilim",
            ["appointment_count"],
            ["RandevuDurumu"],
            "distribution",
        ),
        (
            "protokol durumuna gore randevu dagilimi",
            ["appointment_count"],
            ["ProtokolIslemState"],
            "distribution",
        ),
        (
            "randevu suresini subelere gore karsilastir",
            ["appointment_duration_average"],
            ["SubeAdi"],
            "duration_analysis",
        ),
        ("cinsiyete gore gelmeme orani", ["no_show_rate"], ["CinsiyetId"], "ratio"),
        ("uyruga gore gerceklesme orani", ["completed_appointment_rate"], ["Uyruk"], "ratio"),
        (
            "randevu tipine gore bekleyenleri say",
            ["waiting_count"],
            ["RandevuTipiAdi"],
            "count",
        ),
        (
            "hizmete gore ortalama randevu suresi",
            ["appointment_duration_average"],
            ["HizmetAdi"],
            "duration_analysis",
        ),
        (
            "sube ve bransa gore randevu sayisi",
            ["appointment_count"],
            ["GenelRandevuBolumAdi", "SubeAdi"],
            "cross_analysis",
        ),
    ],
)
def test_real_usage_comparison_questions_map_to_requested_columns(
    question, metrics, dimensions, analysis_type
):
    plan = plan_for(question)

    assert plan.metrics == metrics
    assert plan.dimensions == dimensions
    assert plan.analysis_type == analysis_type

    sql = sql_for(question)
    for dimension in dimensions:
        assert "GROUP BY" in sql
        assert dimension in sql
    for metric in metrics:
        assert f"AS {metric}" in sql
    assert "HastaAdi" not in sql
    assert "HastaSoyadi" not in sql


@pytest.mark.parametrize(
    "question",
    [
        "hasta maillerini goster",
        "hastalarin email adreslerini listele",
    ],
)
def test_removed_email_field_is_not_turned_into_generic_appointment_list(question):
    plan = plan_for(question)

    assert plan.answerable is False
    assert "E-posta" in (plan.answerability_reason or "")

    built = DeterministicSQLBuilder().build(plan)
    assert not hasattr(built, "sql")
