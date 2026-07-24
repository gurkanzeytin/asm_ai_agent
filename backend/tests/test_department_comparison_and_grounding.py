"""Composite department grounding + explicit comparison pairs (2026-07-24).

Covers the fixes for the benchmark failures observed on 2026-07-23:
- interrogative words ("Kaç", "Hangi") mistaken for value mentions,
- empty/dirty DB values grounding via prefix match,
- GenelRandevuBolumAdi composite values (equality never matches an atomic
  department -> delimiter-bounded containment),
- "X ile Y" / "X mi Y mi" comparison pairs resolving BOTH sides,
- benchmark scorer crediting controlled out-of-scope degradations.
"""

import pytest

from app.database_intelligence.value_catalog import _split_composite_values
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan, ResolvedFilterPlan
from app.planning.value_resolver import (
    extract_candidate_phrases,
    extract_comparison_pair,
    resolve_value,
)
from app.services.deterministic_sql_builder import DeterministicSQLBuilder
from tools.benchmark.metrics import Outcome, QuestionRun, Reason, classify


def _plan(**overrides) -> QueryPlan:
    defaults = dict(question="test")
    defaults.update(overrides)
    return QueryPlan(**defaults)


# ── interrogative words are never value candidates ──────────────────────────


class TestQuestionWordCandidates:
    def test_kac_doktor_var_yields_no_candidate(self):
        assert extract_candidate_phrases("Kaç doktor var?") == {}

    def test_hangi_bolum_yields_no_candidate(self):
        assert extract_candidate_phrases("Hangi bölüm daha yoğun?") == {}

    def test_real_department_mention_still_extracts(self):
        result = extract_candidate_phrases("Psikiyatri bölümündeki randevuları göster.")
        assert result == {"department": ["Psikiyatri"]}


# ── empty-value guards in the pure matcher ──────────────────────────────────


class TestEmptyValueGuards:
    def test_empty_input_never_grounds(self):
        result = resolve_value("department", ", ", ["Kardiyoloji"])
        assert result.grounded is False
        assert result.match_type == "no_match"

    def test_empty_candidate_never_prefix_matches(self):
        # A dirty DB value ('') must not swallow every input via prefix match.
        result = resolve_value("department", "Hangi", ["", "Kardiyoloji"])
        assert result.matched_value != ""
        assert result.grounded is False


# ── composite department values split into atomic parts ─────────────────────


class TestCompositeSplitting:
    def test_split_and_dedupe(self):
        values = [
            "Kardiyoloji, ",
            "Genel Cerrahi, Ameliyathane, Ameliyathane, ",
            "",
        ]
        assert _split_composite_values(values) == [
            "Kardiyoloji",
            "Genel Cerrahi",
            "Ameliyathane",
        ]

    def test_atomic_resolution_after_split(self):
        atomic = _split_composite_values(["Psikiyatri, ", "Kardiyoloji, Psikiyatri, "])
        result = resolve_value("department", "Psikiyatri", atomic)
        assert result.matched_value == "Psikiyatri"
        assert result.grounded is True


# ── comparison pair extraction ──────────────────────────────────────────────


class TestComparisonPair:
    def test_ile_pattern(self):
        pair = extract_comparison_pair("Kardiyoloji ile Psikiyatri'yi karşılaştır.")
        assert pair == ("Kardiyoloji", "Psikiyatri")

    def test_mi_pattern(self):
        pair = extract_comparison_pair("Hangi bölüm daha yoğun: Kardiyoloji mi Psikiyatri mi?")
        assert pair == ("Kardiyoloji", "Psikiyatri")

    def test_no_comparison_marker_returns_none(self):
        assert extract_comparison_pair("Ahmet ile görüştüm.") is None

    def test_question_words_never_form_a_pair(self):
        assert extract_comparison_pair("Hangi bölüm ile Ne karşılaştırılır?") is None

    def test_lowercase_mentions_are_ignored(self):
        assert extract_comparison_pair("dün ile bugünü karşılaştır") is None


# ── deterministic builder: containment predicate ────────────────────────────


class TestDepartmentContainmentSQL:
    def test_single_department_filter_renders_containment(self):
        plan = _plan(
            question="Kardiyoloji bölümündeki randevu sayısı",
            analysis_type="count",
            metrics=["appointment_count"],
            department_filter="Kardiyoloji",
        )
        built = DeterministicSQLBuilder().build(plan)
        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "GenelRandevuBolumAdi = " not in built.sql
        assert (
            "',' + REPLACE(GenelRandevuBolumAdi, ', ', ',') + ',' LIKE N'%,Kardiyoloji,%'"
            in built.sql
        )

    def test_grounded_pair_renders_or_containment(self):
        plan = _plan(
            question="Kardiyoloji ile Psikiyatri'yi karşılaştır",
            analysis_type="count",
            metrics=["appointment_count"],
            dimensions=["GenelRandevuBolumAdi"],
            resolved_filters={
                "department": ResolvedFilterPlan(
                    field="department",
                    values=["Kardiyoloji", "Psikiyatri"],
                    grounded=True,
                    confidence=0.95,
                    match_type="comparison_pair",
                )
            },
        )
        built = DeterministicSQLBuilder().build(plan)
        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "LIKE N'%,Kardiyoloji,%'" in built.sql
        assert "LIKE N'%,Psikiyatri,%'" in built.sql
        assert " OR " in built.sql
        assert "IN (" not in built.sql

    def test_compliance_accepts_containment_form(self):
        plan = _plan(
            question="Kardiyoloji bölümü",
            department_filter="Kardiyoloji",
        )
        sql = (
            "SELECT COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu "
            "WHERE ',' + REPLACE(GenelRandevuBolumAdi, ', ', ',') + ',' "
            "LIKE N'%,Kardiyoloji,%';"
        )
        result = PlanComplianceValidator().check(sql, plan)
        assert not any("department filter" in issue for issue in result.missing)

    def test_compliance_still_flags_missing_department_filter(self):
        plan = _plan(question="Kardiyoloji bölümü", department_filter="Kardiyoloji")
        sql = "SELECT COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu;"
        result = PlanComplianceValidator().check(sql, plan)
        assert any("department filter" in issue for issue in result.missing)


# ── deterministic entity comparison (CASE'li çift sayım) ────────────────────


class TestEntityComparisonSQL:
    def _pair_plan(self, **overrides) -> QueryPlan:
        defaults = dict(
            question="Kardiyoloji ile Psikiyatri'yi karşılaştır",
            analysis_type="comparison",
            metrics=["appointment_count"],
            aggregation="COUNT(*)",
            department_filter="Kardiyoloji",
            resolved_filters={
                "department": ResolvedFilterPlan(
                    field="department",
                    values=["Kardiyoloji", "Psikiyatri"],
                    grounded=True,
                    confidence=0.95,
                    match_type="comparison_pair",
                )
            },
        )
        defaults.update(overrides)
        return QueryPlan(**defaults)

    def test_pair_plan_builds_conditional_counts(self):
        built = DeterministicSQLBuilder().build(self._pair_plan())
        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert built.result_schema == "EntityComparisonResult"
        assert "N'Kardiyoloji' AS current_entity_label" in built.sql
        assert "N'Psikiyatri' AS baseline_entity_label" in built.sql
        assert built.sql.count("SUM(CASE WHEN") >= 2
        assert "COUNT(*) AS comparison_total_count" in built.sql
        assert "GROUP BY" not in built.sql
        # Pair conditions live in the CASEs; WHERE restricts to either entity.
        assert " OR " in built.sql

    def test_pair_plan_passes_compliance(self):
        plan = self._pair_plan()
        built = DeterministicSQLBuilder().build(plan)
        result = PlanComplianceValidator().check(
            built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
        )
        assert result.compliant, result.missing

    def test_comparison_without_pair_is_unsupported(self):
        plan = self._pair_plan(resolved_filters={})
        built = DeterministicSQLBuilder().build(plan)
        assert not hasattr(built, "sql")
        assert "grounded two-value entity pair" in built.reason

    def test_branch_pair_uses_equality(self):
        plan = self._pair_plan(
            question="Gebze ile Ataşehir'i karşılaştır",
            department_filter=None,
            branch_filters=["Gebze Şubesi", "Ataşehir Şubesi"],
            resolved_filters={
                "branch": ResolvedFilterPlan(
                    field="branch",
                    values=["Gebze Şubesi", "Ataşehir Şubesi"],
                    grounded=True,
                    confidence=0.95,
                    match_type="comparison_pair",
                )
            },
        )
        built = DeterministicSQLBuilder().build(plan)
        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "SubeAdi = N'Gebze Şubesi'" in built.sql
        assert "SubeAdi = N'Ataşehir Şubesi'" in built.sql


class TestEntityComparisonPresentation:
    def test_renderer_names_the_busier_entity(self):
        from datetime import datetime

        from app.application_models.workflow_models import QueryResult
        from app.reporting.report_classifier import ReportType
        from app.reporting.template_renderer import TemplateReportRenderer

        row = {
            "current_entity_label": "Kardiyoloji",
            "baseline_entity_label": "Psikiyatri",
            "comparison_total_count": 150,
            "current_entity_count": 100,
            "baseline_entity_count": 50,
            "absolute_change": 50,
            "percentage_change": 100.0,
        }
        result = QueryResult(
            columns=list(row.keys()),
            rows=[row],
            row_count=1,
            execution_time_ms=1.0,
            success=True,
            executed_at=datetime.now(),
            database_provider="mssql",
        )
        rendered = TemplateReportRenderer().render(ReportType.SINGLE_ROW, result)
        assert rendered is not None
        assert rendered.template_name == "entity_comparison"
        assert "Kardiyoloji daha yoğun" in rendered.markdown

    def test_tie_is_stated_as_tie(self):
        from datetime import datetime

        from app.application_models.workflow_models import QueryResult
        from app.reporting.report_classifier import ReportType
        from app.reporting.template_renderer import TemplateReportRenderer

        row = {
            "current_entity_label": "A",
            "baseline_entity_label": "B",
            "current_entity_count": 5,
            "baseline_entity_count": 5,
            "absolute_change": 0,
        }
        result = QueryResult(
            columns=list(row.keys()),
            rows=[row],
            row_count=1,
            execution_time_ms=1.0,
            success=True,
            executed_at=datetime.now(),
            database_provider="mssql",
        )
        rendered = TemplateReportRenderer().render(ReportType.SINGLE_ROW, result)
        assert rendered is not None
        assert "eşit yoğunlukta" in rendered.markdown


# ── "kaç X var" scalar distinct counts ──────────────────────────────────────


class TestScalarDistinctCounts:
    @staticmethod
    def _plan_for(question: str) -> QueryPlan:
        from app.database_intelligence.models import ViewMetadata
        from app.planning.planner import QueryPlanner
        from app.services.query_analyzer import QueryAnalyzer

        analysis = QueryAnalyzer().analyze(question)
        return QueryPlanner().build_plan(
            question, analysis, tables=[], views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])]
        )

    def test_kac_doktor_var_is_a_single_scalar(self):
        plan = self._plan_for("Kaç doktor var?")
        assert plan.metrics == ["unique_doctor_count"]
        assert plan.dimensions == []
        built = DeterministicSQLBuilder().build(plan)
        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "COUNT(DISTINCT DoktorId) AS unique_doctor_count" in built.sql
        assert "GROUP BY" not in built.sql

    def test_kac_hasta_var_is_a_single_scalar(self):
        plan = self._plan_for("Kaç hasta var?")
        assert plan.metrics == ["unique_patient_count"]
        assert plan.dimensions == []

    def test_explicit_grouping_keeps_the_dimension(self):
        plan = self._plan_for("Doktorlara göre randevu dağılımını göster.")
        assert plan.dimensions == ["GenelRandevuKaynakAdi"]
        assert plan.metrics == ["appointment_count"]

    def test_scalar_count_leaves_no_projection(self):
        # Regression (full benchmark 2026-07-24): a leftover display-column
        # projection made compliance reject the scalar SQL entirely.
        plan = self._plan_for("Kaç doktor var?")
        assert plan.projection == []
        built = DeterministicSQLBuilder().build(plan)
        check = PlanComplianceValidator().check(
            built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
        )
        assert check.compliant, check.missing

    def test_grouped_doctor_count_projects_the_dimension(self):
        plan = self._plan_for("Bölümlerin doktor sayılarını karşılaştır.")
        assert plan.metrics == ["unique_doctor_count"]
        assert plan.dimensions == ["GenelRandevuBolumAdi"]
        assert plan.projection == ["GenelRandevuBolumAdi"]
        built = DeterministicSQLBuilder().build(plan)
        assert hasattr(built, "sql"), getattr(built, "reason", "")
        check = PlanComplianceValidator().check(
            built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
        )
        assert check.compliant, check.missing

    def test_filtered_department_doctor_count_builds(self):
        plan = self._plan_for("Kardiyoloji bölümünde kaç doktor çalışıyor?")
        assert plan.metrics == ["unique_doctor_count"]
        built = DeterministicSQLBuilder().build(plan)
        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "COUNT(DISTINCT DoktorId)" in built.sql
        assert "LIKE N'%,Kardiyoloji,%'" in built.sql


# ── benchmark scorer: graceful degradations ─────────────────────────────────


def _bench_run(**overrides) -> QuestionRun:
    base = dict(
        model="m",
        question_id=1,
        category="count",
        question="Kaç randevu var?",
        generated_sql="SELECT COUNT(*) FROM dbo.vw_RandevuRaporu;",
        execution_success=True,
        rows_returned=1,
    )
    base.update(overrides)
    return QuestionRun(**base)


class TestBenchmarkScorer:
    def test_out_of_view_entity_with_graceful_outcome_is_success(self):
        run = _bench_run(
            question="Kaç oda var?",
            generated_sql=None,
            execution_success=False,
            rows_returned=0,
            workflow_outcome="ASK_CLARIFICATION",
        )
        outcome, reason = classify(run)
        assert outcome == Outcome.SUCCESS
        assert reason == Reason.EXPECTED_OUT_OF_SCOPE

    def test_out_of_view_entity_without_graceful_outcome_still_fails(self):
        run = _bench_run(
            question="Sigorta şirketlerini göster.",
            category="listing",
            generated_sql=None,
            execution_success=False,
            rows_returned=0,
            workflow_outcome=None,
        )
        outcome, reason = classify(run)
        assert outcome == Outcome.FAILED
        assert reason == Reason.SQL_GENERATION_FAILED

    def test_answerable_question_clarification_is_partial(self):
        run = _bench_run(
            generated_sql=None,
            execution_success=False,
            rows_returned=0,
            workflow_outcome="ASK_CLARIFICATION",
        )
        outcome, reason = classify(run)
        assert outcome == Outcome.PARTIAL
        assert reason == Reason.UNEXPECTED_CLARIFICATION
