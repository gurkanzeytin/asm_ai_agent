"""AG-022 — Query Planning Engine regression tests.

Covers plan construction for multi-constraint questions (date + department,
date + ranking, department + ranking, three simultaneous filters), negative /
comparison / aggregation queries, context-continuation style questions,
constraint preservation, minimal FK join paths, and SQL compliance checking.
Fully deterministic — no LLM, no database.
"""

import pytest

from app.database_intelligence.models import (
    ColumnMetadata,
    ForeignKeyMetadata,
    TableMetadata,
)
from app.planning.compliance import PlanComplianceValidator
from app.planning.planner import QueryPlanner, format_plan_for_prompt
from app.services.query_analyzer import QueryAnalyzer


def col(name: str, pk: bool = False) -> ColumnMetadata:
    return ColumnMetadata(name=name, type_name="TEXT", nullable=True, primary_key=pk)


def fk(cols: list[str], table: str, refs: list[str]) -> ForeignKeyMetadata:
    return ForeignKeyMetadata(
        constrained_columns=cols, referred_table=table, referred_columns=refs
    )


@pytest.fixture()
def tables() -> list[TableMetadata]:
    return [
        TableMetadata(
            name="randevular",
            columns=[col("id", True), col("randevu_tarihi"), col("doktor_id"), col("hasta_id")],
            primary_keys=["id"],
            foreign_keys=[fk(["doktor_id"], "doktorlar", ["id"]), fk(["hasta_id"], "hastalar", ["id"])],
        ),
        TableMetadata(
            name="doktorlar",
            columns=[col("id", True), col("ad_soyad"), col("bolum_id")],
            primary_keys=["id"],
            foreign_keys=[fk(["bolum_id"], "bolumler", ["id"])],
        ),
        TableMetadata(
            name="bolumler",
            columns=[col("id", True), col("bolum_adi")],
            primary_keys=["id"],
            foreign_keys=[],
        ),
        TableMetadata(
            name="hastalar",
            columns=[col("id", True), col("ad_soyad")],
            primary_keys=["id"],
            foreign_keys=[],
        ),
    ]


@pytest.fixture()
def planner() -> QueryPlanner:
    return QueryPlanner()


def build(planner: QueryPlanner, question: str, tables: list[TableMetadata]):
    analysis = QueryAnalyzer().analyze(question)
    return planner.build_plan(question, analysis, tables)


# ─────────────────────────────────────────────
# Multi-constraint planning
# ─────────────────────────────────────────────

class TestMultiConstraintPlans:
    def test_date_plus_department_plus_output(self, planner, tables):
        """The AG-022 flagship case: every constraint must survive."""
        plan = build(
            planner,
            "Bugünkü randevular içerisinden çocuk sağlığındaki doktorları listele",
            tables,
        )
        assert plan.output_entity == "Doctor"
        assert plan.fact_entity == "Appointment"
        assert plan.department_filter == "Cocuk Sagligi"
        assert len(plan.date_filters) == 1
        assert plan.date_filters[0].column == "randevu_tarihi"
        assert plan.distinct
        assert plan.projection == ["ad_soyad"]
        joins = [step.render() for step in plan.join_path]
        assert "randevular.doktor_id -> doktorlar.id" in joins
        assert "doktorlar.bolum_id -> bolumler.id" in joins

    def test_date_plus_ranking(self, planner, tables):
        plan = build(planner, "Bugün en yoğun doktor kim?", tables)
        assert len(plan.date_filters) == 1
        assert plan.ranking == "DESC"
        assert plan.output_entity == "Doctor"
        assert plan.fact_entity == "Appointment"  # implied by 'yoğun'

    def test_department_plus_ranking(self, planner, tables):
        plan = build(planner, "Kardiyolojide en yoğun doktor kim?", tables)
        assert plan.department_filter == "Kardiyoloji"
        assert plan.ranking == "DESC"

    def test_three_simultaneous_filters(self, planner, tables):
        plan = build(
            planner, "Bugün Kardiyolojide ilk 5 doktoru randevu sayısına göre göster", tables
        )
        assert len(plan.date_filters) == 1
        assert plan.department_filter == "Kardiyoloji"
        assert plan.limit == 5
        assert plan.constraint_count() >= 3

    def test_ascending_ranking(self, planner, tables):
        plan = build(planner, "En az randevusu olan doktoru göster", tables)
        assert plan.ranking == "ASC"


# ─────────────────────────────────────────────
# Query styles
# ─────────────────────────────────────────────

class TestQueryStyles:
    def test_negative_query_keeps_negation_filter(self, planner, tables):
        plan = build(planner, "Randevusu olmayan doktorları listele", tables)
        assert any("NEGATION" in f for f in plan.extra_filters)

    def test_comparison_query_typed(self, planner, tables):
        plan = build(planner, "Bölümlere göre randevuları karşılaştır", tables)
        assert plan.analysis_type == "comparison"

    def test_aggregation_query(self, planner, tables):
        plan = build(planner, "Bugün kaç randevu oluşturuldu?", tables)
        assert plan.aggregation == "COUNT"
        assert plan.output_entity == "Appointment"
        assert plan.projection == []  # scalar answer needs no descriptive column
        assert not plan.distinct

    def test_context_continuation_style_question(self, planner, tables):
        """Resolved follow-ups from the context engine plan like normal questions."""
        plan = build(planner, "bugun Kardiyoloji doktorlari arasindan en yogun olan kim", tables)
        assert len(plan.date_filters) == 1
        assert plan.department_filter == "Kardiyoloji"
        assert plan.ranking == "DESC"

    def test_single_constraint_stays_minimal(self, planner, tables):
        plan = build(planner, "Doktorları listele", tables)
        assert plan.date_filters == []
        assert plan.department_filter is None
        assert plan.ranking is None
        assert plan.limit is None
        assert plan.join_path == []
        assert plan.output_table == "doktorlar"

    def test_suffixed_date_forms_detected(self, planner, tables):
        plan = build(planner, "Bugünkü randevuları göster", tables)
        assert len(plan.date_filters) == 1

    def test_dunya_is_not_a_date(self, planner, tables):
        plan = build(planner, "Dünya sağlık günü randevularını göster", tables)
        assert all(d.expression != "dun" for d in plan.date_filters)


# ─────────────────────────────────────────────
# Join path
# ─────────────────────────────────────────────

class TestJoinPath:
    def test_no_join_guessing_without_fk(self, planner):
        """No declared FK between tables — the planner must not invent a join."""
        isolated = [
            TableMetadata(name="doktorlar", columns=[col("id", True), col("ad_soyad")], primary_keys=["id"], foreign_keys=[]),
            TableMetadata(name="randevular", columns=[col("id", True), col("randevu_tarihi")], primary_keys=["id"], foreign_keys=[]),
        ]
        plan = build(planner, "Bugünkü randevulardaki doktorları göster", isolated)
        assert plan.join_path == []

    def test_patient_to_doctor_via_appointments(self, planner, tables):
        plan = build(planner, "Hastaları muayene eden doktorları göster", tables)
        joins = [step.render() for step in plan.join_path]
        assert "randevular.hasta_id -> hastalar.id" in joins or "randevular.doktor_id -> doktorlar.id" in joins


# ─────────────────────────────────────────────
# Prompt contract
# ─────────────────────────────────────────────

class TestPromptContract:
    def test_plan_renders_every_constraint(self, planner, tables):
        plan = build(
            planner,
            "Bugünkü randevular içerisinden çocuk sağlığındaki doktorları listele",
            tables,
        )
        section = format_plan_for_prompt(plan)
        assert "DISTINCT" in section
        assert "randevu_tarihi" in section
        assert "Cocuk Sagligi" in section
        assert "randevular.doktor_id -> doktorlar.id" in section

    def test_empty_plan_renders_nothing(self, planner, tables):
        plan = build(planner, "merhaba nasılsın", tables)
        assert format_plan_for_prompt(plan) == ""


# ─────────────────────────────────────────────
# Compliance validation
# ─────────────────────────────────────────────

class TestCompliance:
    def setup_method(self):
        self.validator = PlanComplianceValidator()

    def _flagship_plan(self, planner, tables):
        return build(
            planner,
            "Bugünkü randevular içerisinden çocuk sağlığındaki doktorları listele",
            tables,
        )

    def test_compliant_sql_passes(self, planner, tables):
        plan = self._flagship_plan(planner, tables)
        sql = (
            "SELECT DISTINCT d.ad_soyad FROM randevular r "
            "JOIN doktorlar d ON r.doktor_id = d.id "
            "JOIN bolumler b ON d.bolum_id = b.id "
            f"WHERE r.randevu_tarihi = '{plan.date_filters[0].start_date}' "
            "AND b.bolum_adi = 'cocuk sagligi';"
        )
        result = self.validator.check(sql, plan)
        assert result.compliant

    def test_dropped_date_filter_detected(self, planner, tables):
        plan = self._flagship_plan(planner, tables)
        sql = (
            "SELECT d.ad_soyad FROM doktorlar d JOIN bolumler b ON d.bolum_id = b.id "
            "WHERE b.bolum_adi = 'cocuk sagligi';"
        )
        result = self.validator.check(sql, plan)
        assert not result.compliant
        assert any("date filter" in item for item in result.missing)
        assert any("join table randevular" in item for item in result.missing)

    def test_dropped_department_detected(self, planner, tables):
        plan = self._flagship_plan(planner, tables)
        sql = (
            "SELECT DISTINCT d.ad_soyad FROM randevular r "
            "JOIN doktorlar d ON r.doktor_id = d.id "
            "JOIN bolumler b ON d.bolum_id = b.id "
            f"WHERE r.randevu_tarihi = '{plan.date_filters[0].start_date}';"
        )
        result = self.validator.check(sql, plan)
        assert any("department" in item for item in result.missing)

    def test_missing_limit_and_order_detected(self, planner, tables):
        plan = build(planner, "En yoğun ilk 3 doktoru göster", tables)
        sql = "SELECT d.ad_soyad FROM doktorlar d;"
        result = self.validator.check(sql, plan)
        assert any("LIMIT 3" in item for item in result.missing)
        assert any("ORDER BY" in item for item in result.missing)

    def test_missing_aggregation_detected(self, planner, tables):
        plan = build(planner, "Bugün kaç randevu oluşturuldu?", tables)
        sql = "SELECT randevu_tarihi FROM randevular WHERE randevu_tarihi = '2026-07-14';"
        result = self.validator.check(sql, plan)
        assert any("COUNT" in item for item in result.missing)

    def test_plan_without_constraints_always_compliant(self, planner, tables):
        plan = build(planner, "Doktorları listele", tables)
        result = self.validator.check("SELECT ad_soyad FROM doktorlar;", plan)
        assert result.compliant


# ─────────────────────────────────────────────
# Performance
# ─────────────────────────────────────────────

class TestPerformance:
    def test_planner_is_fast(self, planner, tables):
        plan = build(
            planner,
            "Bugünkü randevular içerisinden çocuk sağlığındaki doktorları listele",
            tables,
        )
        assert plan.planner_ms < 50.0
