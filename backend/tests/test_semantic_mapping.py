"""Deterministic tests for user-language → dbo.vw_RandevuRaporu column mapping.

Covers the central semantic metadata (resources/view_semantics.json), its
accessors (app/semantics/view_mapping.py), and the QueryPlanner's view-aware
resolution. No LLM calls, no database connections, no real patient values.
"""

import pytest

from app.database_intelligence.models import ViewMetadata
from app.planning.compliance import PlanComplianceValidator
from app.planning.planner import QueryPlanner
from app.semantics import view_mapping
from app.services.query_analyzer import QueryAnalyzer

VIEW_NAME = "dbo.vw_RandevuRaporu"
VIEW = ViewMetadata(name=VIEW_NAME, columns=[])


def plan_for(question: str):
    analysis = QueryAnalyzer().analyze(question)
    return QueryPlanner().build_plan(question, analysis, tables=[], views=[VIEW])


def date_columns(plan) -> set:
    return {date_filter.column for date_filter in plan.date_filters}


# ---------------------------------------------------------------------------
# Concept → column resolution through the planner (the 12 focus questions)
# ---------------------------------------------------------------------------


def test_top_doctors_maps_to_kaynak_adi():
    plan = plan_for("En çok randevu alan 10 doktoru göster.")
    assert plan.output_table == VIEW_NAME
    assert plan.projection == ["GenelRandevuKaynakAdi"]
    assert plan.limit == 10
    assert plan.join_path == []
    # negative: doctor must not resolve to the creator or a patient field
    assert "RandevuyuVeren" not in plan.projection
    assert "HastaAdi" not in plan.projection


def test_doctor_grouping_maps_to_kaynak_adi():
    plan = plan_for("Hekim bazında randevu sayılarını getir.")
    assert plan.projection == ["GenelRandevuKaynakAdi"]
    assert plan.aggregation == "COUNT(*)"


def test_today_child_health_doctors():
    plan = plan_for("Bugünkü çocuk sağlığı doktorlarını listele.")
    assert plan.projection == ["GenelRandevuKaynakAdi"]
    assert date_columns(plan) == {"BaslangicTarihi"}
    assert plan.department_filter is not None


def test_creators_map_to_randevuyu_veren():
    plan = plan_for("En çok randevu oluşturan kişileri göster.")
    assert plan.projection == ["RandevuyuVeren"]
    # negative: the creator is never the doctor/resource column
    assert "GenelRandevuKaynakAdi" not in plan.projection


def test_busiest_departments_map_to_bolum_adi():
    plan = plan_for("En yoğun 5 bölümü göster.")
    assert plan.projection == ["GenelRandevuBolumAdi"]
    assert plan.limit == 5
    # negative: department is not the category and not the branch
    assert "KategoriAdi" not in plan.projection
    assert "SubeAdi" not in plan.projection


def test_branch_grouping_maps_to_sube_adi():
    plan = plan_for("Şube bazında randevu sayılarını getir.")
    assert plan.projection == ["SubeAdi"]
    assert plan.aggregation == "COUNT(*)"
    # negative: branch is not the department column
    assert "GenelRandevuBolumAdi" not in plan.projection


def test_todays_appointments_use_baslangic_tarihi():
    plan = plan_for("Bugünkü randevuları getir.")
    assert date_columns(plan) == {"BaslangicTarihi"}
    # negative: appointment date questions never use the record-creation date
    assert "CreatedDate" not in date_columns(plan)


def test_created_today_uses_created_date():
    plan = plan_for("Bugün oluşturulan randevuları getir.")
    assert date_columns(plan) == {"CreatedDate"}
    # negative: creation-date questions never use the appointment start date
    assert "BaslangicTarihi" not in date_columns(plan)


def test_protocol_opened_today_uses_protokol_acilis():
    plan = plan_for("Bugün protokolü açılan randevuları getir.")
    assert date_columns(plan) == {"ProtokolAcilisTarihi"}


def test_distinct_patients_uses_count_distinct_hasta_id():
    plan = plan_for("Kaç farklı hasta randevu almış?")
    assert plan.aggregation == "COUNT(DISTINCT HastaId)"
    assert plan.projection == []


def test_completed_appointment_count_uses_count_star_and_status():
    plan = plan_for("Gerçekleşen randevuların sayısı kaç?")
    assert plan.aggregation == "COUNT(*)"
    assert any("RandevuDurumu = 'Gerçekleşti'" in flt for flt in plan.extra_filters)


def test_appointment_type_distribution_groups_by_tipi_adi():
    plan = plan_for("Randevu tiplerine göre dağılımı getir.")
    assert plan.projection == ["RandevuTipiAdi"]
    assert plan.aggregation == "COUNT(*)"


# ---------------------------------------------------------------------------
# Central metadata accessors
# ---------------------------------------------------------------------------


def test_concept_columns_from_central_metadata():
    assert view_mapping.concept_column("Doctor", VIEW_NAME) == "GenelRandevuKaynakAdi"
    assert view_mapping.concept_column("Creator", VIEW_NAME) == "RandevuyuVeren"
    assert view_mapping.concept_column("Department", VIEW_NAME) == "GenelRandevuBolumAdi"
    assert view_mapping.concept_column("Branch", VIEW_NAME) == "SubeAdi"
    assert view_mapping.concept_column("Patient", VIEW_NAME) == "HastaId"


def test_date_column_resolution_rules():
    assert view_mapping.resolve_date_column("bugunku randevular") == "BaslangicTarihi"
    assert view_mapping.resolve_date_column("bugun olusturulan randevular") == "CreatedDate"
    assert view_mapping.resolve_date_column("protokolu bugun acilanlar") == "ProtokolAcilisTarihi"


def test_measure_resolution():
    assert view_mapping.resolve_measure("kac farkli hasta") == "COUNT(DISTINCT HastaId)"
    assert view_mapping.resolve_measure("randevu sayisi kac") == "COUNT(*)"
    assert view_mapping.resolve_measure("ortalama sure") is None


def test_grounding_mapping_lines_cover_key_concepts():
    rendered = "\n".join(view_mapping.concept_mapping_lines(VIEW_NAME))
    assert "GenelRandevuKaynakAdi" in rendered
    assert "RandevuyuVeren" in rendered
    assert "GenelRandevuBolumAdi" in rendered
    assert "SubeAdi" in rendered
    assert "CreatedDate" in rendered
    assert "COUNT(DISTINCT HastaId)" in rendered


# ---------------------------------------------------------------------------
# Plan compliance under T-SQL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT TOP (10) GenelRandevuKaynakAdi, COUNT(*) AS adet FROM dbo.vw_RandevuRaporu "
        "GROUP BY GenelRandevuKaynakAdi ORDER BY adet DESC;",
        "SELECT TOP 10 GenelRandevuKaynakAdi, COUNT(*) AS adet FROM dbo.vw_RandevuRaporu "
        "GROUP BY GenelRandevuKaynakAdi ORDER BY adet DESC;",
    ],
)
def test_compliance_accepts_tsql_top(sql):
    plan = plan_for("En çok randevu alan 10 doktoru göster.")
    result = PlanComplianceValidator().check(sql, plan)
    assert result.compliant, result.missing


def test_compliance_requires_distinct_for_distinct_patient_count():
    plan = plan_for("Kaç farklı hasta randevu almış?")
    validator = PlanComplianceValidator()
    good = validator.check("SELECT COUNT(DISTINCT HastaId) FROM dbo.vw_RandevuRaporu;", plan)
    assert good.compliant, good.missing
    bad = validator.check("SELECT COUNT(*) FROM dbo.vw_RandevuRaporu;", plan)
    assert not bad.compliant
