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
    extract_comparison_entities,
    extract_comparison_pair,
    resolve_value,
)
from app.services.deterministic_sql_builder import (
    _DEPARTMENT_SPLIT_ALIAS,
    DeterministicSQLBuilder,
)
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


class TestPronounInflectionsAreNeverValueCandidates:
    """"Bunu şubeye göre kır" ("break this down by branch") walked back from
    the "şube" cue straight into "Bunu" and asked the user to disambiguate
    it as a BRANCH NAME ("'Bunu' değerine uygun bir şube bulunamadı...")
    instead of resolving as a follow-up pronoun - only the nominative
    demonstratives ("bu"/"şu"/"o") were in the stopset, not their inflected
    forms (2026-07-27, live multi-turn testing)."""

    def test_accusative_pronoun_yields_no_candidate(self):
        assert extract_candidate_phrases("Bunu şubeye göre kır") == {}
        assert extract_candidate_phrases("Onu bölüme göre göster") == {}
        assert extract_candidate_phrases("Şunu doktora göre kır") == {}

    def test_other_inflections_yield_no_candidate(self):
        assert extract_candidate_phrases("Buna göre şubeleri sırala") == {}
        assert extract_candidate_phrases("Onun bölümünü göster") == {}

    def test_real_department_starting_like_the_o_pronoun_still_extracts(self):
        # A startswith root for "o" would have swallowed "Onkoloji" - this is
        # exactly why the inflected forms are listed as exact tokens instead.
        result = extract_candidate_phrases("Onkoloji bölümündeki randevuları göster.")
        assert result == {"department": ["Onkoloji"]}

    def test_real_branch_mention_still_extracts(self):
        result = extract_candidate_phrases("TEST ASM Gebze şubesindeki randevuları göster.")
        assert result == {"branch": ["TEST ASM Gebze"]}


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


# ── GROUP BY over the composite department column splits it first ─────────


class TestDepartmentGroupBySplitting:
    """"En az/çok randevusu olan N bölümü göster" - GROUP BY on the raw
    composite GenelRandevuBolumAdi column used to produce one row per
    distinct COMBINATION (425+ of them) instead of one row per atomic
    department: a bottom-N question returned nonsense like "Nöroşirurji,
    Plastik ve Rekonstruktif Cerrahi," as if it were a single department
    (2026-07-27, live multi-turn testing). Fixed via an XML-based CROSS
    APPLY split (STRING_SPLIT is unavailable - the live database's
    compatibility level is 110, below the 130 it requires)."""

    def _grouped_plan(self, **overrides) -> QueryPlan:
        defaults = dict(
            question="Bölümlere göre randevu sayısını göster",
            analysis_type="distribution",
            metrics=["appointment_count"],
            dimensions=["GenelRandevuBolumAdi"],
        )
        defaults.update(overrides)
        return QueryPlan(**defaults)

    def test_group_by_uses_the_split_alias_not_the_raw_column(self):
        built = DeterministicSQLBuilder().build(self._grouped_plan())

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "GROUP BY dept_atomic.value" in built.sql
        assert "GROUP BY GenelRandevuBolumAdi" not in built.sql
        assert "CROSS APPLY" in built.sql
        assert ".nodes(" in built.sql
        # The output column is still named GenelRandevuBolumAdi so downstream
        # presentation/label resolution is unaffected by the SQL-shape change.
        assert "dept_atomic.value AS GenelRandevuBolumAdi" in built.sql

    def test_empty_and_trailing_comma_fragments_are_excluded(self):
        built = DeterministicSQLBuilder().build(self._grouped_plan())

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "dept_atomic.value <> ''" in built.sql

    def test_ampersand_and_angle_brackets_are_stripped_not_entity_escaped(self):
        """`&`/`<`/`>` must be dropped, not XML-entity-escaped (`&amp;` etc.):
        standard entities end in `;`, and the shared LLM-output SQL extractor
        (OutputParser.parse_sql) truncates at the FIRST semicolon anywhere in
        the text - entity-escaping silently cut the query short mid-string
        the first time this was live-tested."""
        built = DeterministicSQLBuilder().build(self._grouped_plan())

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "&amp;" not in built.sql
        assert "&lt;" not in built.sql
        assert "&gt;" not in built.sql

        from app.parsers.output_parser import OutputParser

        assert OutputParser().parse_sql(built.sql) == built.sql

    def test_split_group_by_passes_compliance_and_validator(self):
        plan = self._grouped_plan()
        built = DeterministicSQLBuilder().build(plan)
        assert hasattr(built, "sql"), getattr(built, "reason", "")

        from app.sql_validator.validator import SQLValidator

        assert SQLValidator().validate(built.sql).valid
        compliance = PlanComplianceValidator().check(
            built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
        )
        assert compliance.compliant, compliance.missing

    def test_bottom_n_ranking_still_applies_top_and_order(self):
        plan = self._grouped_plan(
            analysis_type="bottom_n", limit=5, ranking="ASC", order="ASC"
        )
        built = DeterministicSQLBuilder().build(plan)

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "TOP (5)" in built.sql
        assert "ORDER BY appointment_count ASC" in built.sql
        assert "GROUP BY dept_atomic.value" in built.sql

    def test_cross_analysis_second_dimension_is_unaffected(self):
        """A second, non-composite dimension alongside the department split
        must survive untouched in both SELECT and GROUP BY."""
        plan = self._grouped_plan(
            analysis_type="cross_analysis", dimensions=["GenelRandevuBolumAdi", "CinsiyetId"]
        )
        built = DeterministicSQLBuilder().build(plan)

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "CinsiyetId AS CinsiyetId" in built.sql
        assert "GROUP BY dept_atomic.value, CinsiyetId" in built.sql

    def test_non_department_dimension_never_gets_the_cross_apply(self):
        """Regression guard: a plan with no department dimension at all must
        render exactly like before - no CROSS APPLY, no behavior change."""
        built = DeterministicSQLBuilder().build(
            self._grouped_plan(dimensions=["SubeAdi"])
        )

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert "CROSS APPLY" not in built.sql
        assert "GROUP BY SubeAdi" in built.sql


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

    def test_ile_pattern_multi_word_right_side(self):
        # 2026-07-24 live bug: the right side used to be truncated to a single
        # token ("Kadın"), which then failed to ground against the real
        # two-word department "Kadın Doğum" and silently dropped the whole
        # comparison.
        pair = extract_comparison_pair("Ortopedi ile Kadın Doğum'u karşılaştır.")
        assert pair == ("Ortopedi", "Kadın Doğum")

    def test_ile_pattern_multi_word_left_and_right(self):
        pair = extract_comparison_pair(
            "Kardiyoloji ile Çocuk Kardiyolojisi'ni randevu sayısı bakımından karşılaştır"
        )
        assert pair == ("Kardiyoloji", "Çocuk Kardiyolojisi")

    def test_ile_pattern_stops_at_department_cue_word(self):
        # The multi-word walk must not swallow a trailing cue noun like
        # "Bölümü" — "bolum" is a _NEVER_CANDIDATE_ROOTS entry precisely so it
        # never gets treated as part of the entity name itself.
        pair = extract_comparison_pair(
            "Kardiyoloji ile Psikiyatri Bölümü'nü karşılaştır."
        )
        assert pair == ("Kardiyoloji", "Psikiyatri")

    def test_mi_pattern_multi_word(self):
        pair = extract_comparison_pair(
            "Hangisi daha yoğun: Ortopedi mi Kadın Doğum mu?"
        )
        assert pair == ("Ortopedi", "Kadın Doğum")


class TestComparisonEntityEnumeration:
    """"A, B ve C" enumerations — only 3+ (the 2-value case stays with
    extract_comparison_pair, whose anchoring is deliberately narrower)."""

    def test_three_entity_enumeration(self):
        assert extract_comparison_entities(
            "Kardiyoloji, Ortopedi ve Nöroloji'yi randevu sayısı bakımından karşılaştır"
        ) == ["Kardiyoloji", "Ortopedi", "Nöroloji"]

    def test_four_entity_enumeration(self):
        assert extract_comparison_entities(
            "Kardiyoloji, Ortopedi, Nöroloji ve Üroloji'yi kıyasla"
        ) == ["Kardiyoloji", "Ortopedi", "Nöroloji", "Üroloji"]

    def test_leading_month_name_is_not_absorbed(self):
        assert extract_comparison_entities(
            "2025 Mayıs ayında Kardiyoloji, Ortopedi ve Nöroloji'yi karşılaştır"
        ) == ["Kardiyoloji", "Ortopedi", "Nöroloji"]

    def test_branch_prefix_is_not_absorbed(self):
        assert extract_comparison_entities(
            "TEST ASM Gebze şubesinde Kardiyoloji, Ortopedi ve Nöroloji'yi karşılaştır"
        ) == ["Kardiyoloji", "Ortopedi", "Nöroloji"]

    def test_two_entity_pair_is_left_to_the_pair_extractor(self):
        assert extract_comparison_entities("Ortopedi ile Kadın Doğum'u karşılaştır") == []

    def test_department_name_containing_ve_stays_below_threshold(self):
        # "Kalp ve Damar Cerrahisi" is a REAL department name whose own "ve"
        # this loose scan mis-splits — the >=3 threshold plus the caller's
        # all-or-nothing grounding rule is what keeps that harmless.
        assert extract_comparison_entities(
            "Kalp ve Damar Cerrahisi bölümünü Ortopedi ile karşılaştır"
        ) == []

    def test_field_cue_enumeration_is_a_multi_value_filter(self):
        # A field cue ("bölümleri") makes a 3+-value list a multi-value FILTER,
        # even without a comparison verb (#4 ileri filtreler, 2026-07-29).
        assert extract_comparison_entities("Kardiyoloji, Ortopedi ve Nöroloji bölümleri") == [
            "Kardiyoloji",
            "Ortopedi",
            "Nöroloji",
        ]

    def test_no_comparison_marker_and_no_field_cue_yields_nothing(self):
        # Neither a comparison verb nor a field cue — not an enumeration.
        assert extract_comparison_entities("Kardiyoloji, Ortopedi ve Nöroloji sayıları") == []


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
        assert "GenelRandevuBolumAdi IN (" not in built.sql

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

    def test_rate_metric_pair_compares_rates_not_counts(self):
        """"Kardiyoloji ile Nöroloji'nin gelmeme ORANINI karşılaştır" must
        compare the two no-show RATES, not their raw appointment counts (live
        2026-07-28: the count pair contract reported 18615 vs 6483 appointments
        for a rate question). A non-count metric delegates to the per-entity
        breakdown, one row per side with its own rate."""
        plan = self._pair_plan(
            question="Kardiyoloji ile Nöroloji'nin gelmeme oranını karşılaştır",
            metrics=["no_show_rate"],
            aggregation=None,
            resolved_filters={
                "department": ResolvedFilterPlan(
                    field="department",
                    values=["Kardiyoloji", "Nöroloji"],
                    grounded=True,
                    confidence=0.95,
                    match_type="comparison_pair",
                )
            },
        )
        built = DeterministicSQLBuilder().build(plan)
        assert hasattr(built, "sql"), getattr(built, "reason", "")
        # Rendered as a per-entity breakdown (DistributionResult), not the
        # count-based EntityComparisonResult pair contract.
        assert built.result_schema == "DistributionResult"
        assert "no_show_rate" in built.sql
        assert "RandevuDurumu = N'Gelmedi'" in built.sql
        assert "current_entity_count" not in built.sql
        # Both departments appear as their own rows.
        assert "Kardiyoloji" in built.sql
        assert "Nöroloji" in built.sql

    def test_count_metric_pair_still_uses_count_contract(self):
        """A volume comparison keeps the absolute/percentage-change pair
        contract — the rate delegation must not swallow the count case."""
        built = DeterministicSQLBuilder().build(self._pair_plan())
        assert built.result_schema == "EntityComparisonResult"
        assert "current_entity_count" in built.sql

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


class TestEntityBreakdownSQL:
    """Three-or-more entity comparison ("Kardiyoloji, Ortopedi ve Nöroloji").

    The pair contract (current_/baseline_ labels + one change figure) cannot
    express three sides. Before this, such a question silently grounded ONLY
    the first department and answered with a plain scalar count for it — no
    comparison, no warning (2026-07-24, live multi-turn testing).
    """

    def _set_plan(self, values: list[str], **overrides) -> QueryPlan:
        defaults = dict(
            question="Kardiyoloji, Ortopedi ve Nöroloji'yi karşılaştır",
            analysis_type="comparison",
            metrics=["appointment_count"],
            aggregation="COUNT(*)",
            resolved_filters={
                "department": ResolvedFilterPlan(
                    field="department",
                    values=values,
                    grounded=True,
                    confidence=0.95,
                    match_type="comparison_pair",
                )
            },
        )
        defaults.update(overrides)
        return QueryPlan(**defaults)

    def test_three_entities_build_one_row_each(self):
        values = ["Kardiyoloji", "Ortopedi", "Nöroloji"]
        built = DeterministicSQLBuilder().build(self._set_plan(values))

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        # Reported as a plain distribution so the existing categorical
        # analytics/insight/chart path renders it with no new contract.
        assert built.result_schema == "DistributionResult"
        assert built.expected_aliases == ["entity_label", "appointment_count"]
        assert built.sql.count("UNION ALL") == 2
        for value in values:
            assert f"N'{value}' AS entity_label" in built.sql
        # NOT a GROUP BY: the department column is composite, so grouping it
        # raw would yield combination rows instead of one row per entity.
        assert "GROUP BY" not in built.sql
        assert "ORDER BY appointment_count DESC" in built.sql

    def test_three_entity_breakdown_passes_compliance(self):
        plan = self._set_plan(["Kardiyoloji", "Ortopedi", "Nöroloji"])
        built = DeterministicSQLBuilder().build(plan)
        result = PlanComplianceValidator().check(
            built.sql, plan, expected_aliases=built.expected_aliases, deterministic=True
        )
        assert result.compliant, result.missing

    def test_each_branch_keeps_the_shared_date_filter(self):
        from app.planning.models import DateFilterPlan

        plan = self._set_plan(
            ["Kardiyoloji", "Ortopedi", "Nöroloji"],
            date_filters=[
                DateFilterPlan(
                    expression="2025",
                    start_date="2025-01-01",
                    end_date="2025-12-31",
                    column="BaslangicTarihi",
                )
            ],
        )
        built = DeterministicSQLBuilder().build(plan)

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert built.sql.count("2025-01-01") == 3

    def test_two_entities_still_use_the_pair_contract(self):
        """Regression guard: the 3+ path must not capture the pair case."""
        built = DeterministicSQLBuilder().build(self._set_plan(["Kardiyoloji", "Ortopedi"]))

        assert hasattr(built, "sql"), getattr(built, "reason", "")
        assert built.result_schema == "EntityComparisonResult"
        assert "UNION ALL" not in built.sql

    def test_multi_metric_breakdown_is_unsupported(self):
        plan = self._set_plan(
            ["Kardiyoloji", "Ortopedi", "Nöroloji"],
            metrics=["appointment_count", "no_show_rate"],
        )
        built = DeterministicSQLBuilder().build(plan)

        assert not hasattr(built, "sql")
        assert "multi-metric entity breakdown" in built.reason


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


@pytest.mark.asyncio
async def test_three_value_department_filter_vs_comparison(monkeypatch):
    """A 3+-value department enumeration is a FILTER (single containment-OR
    total) in a plain context, but a per-entity breakdown when a comparison
    verb is present — and all three values ground, not just the ends (#4 ileri
    filtreler, 2026-07-29)."""
    from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
    from app.agent.state import AgentState
    from app.database_intelligence.models import ViewMetadata
    from app.services.query_analyzer import QueryAnalyzer
    from app.planning.planner import QueryPlanner

    depts = ["Kardiyoloji", "Nöroloji", "Ortopedi"]

    class _R:
        async def resolve(self, field, phrase):
            return resolve_value(field, phrase, depts if field == "department" else [])

    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    node = ResolveFilterValuesNode(_R())

    async def _run(question: str):
        plan = QueryPlanner().build_plan(question, QueryAnalyzer().analyze(question), [], views=[view])
        state = await node.execute(AgentState(question=question, raw_question=question, query_plan=plan))
        return state.query_plan

    filt = await _run("2024 Kardiyoloji, Noroloji ve Ortopedi bolumlerinde toplam kac randevu var")
    assert filt.analysis_type != "comparison"
    assert set(filt.resolved_filters["department"].values) == set(depts)
    built = DeterministicSQLBuilder().build(filt)
    # A single containment-OR filter, one row — every department appears.
    assert all(d in built.sql for d in ("Kardiyoloji", "Nöroloji", "Ortopedi"))
    assert "entity_label" not in built.sql

    cmp = await _run("2024 Kardiyoloji, Noroloji ve Ortopedi yi karsilastir")
    assert cmp.analysis_type == "comparison"


@pytest.mark.asyncio
async def test_department_exclusion_breakdown_and_total(monkeypatch):
    """"X hariç ..." grounds the excluded name and drops the positive
    department filter it mis-parsed into, so filter+exclusion never cancel to
    zero rows. A breakdown excludes the ATOMIC value (composite rows keep their
    other departments); a plain total excludes at the row level (#4 ileri
    filtreler, 2026-07-29)."""
    from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
    from app.agent.state import AgentState
    from app.database_intelligence.models import ViewMetadata
    from app.services.query_analyzer import QueryAnalyzer
    from app.planning.planner import QueryPlanner

    depts = ["Kardiyoloji", "Radyoloji", "Nöroloji", "Ortopedi"]

    class _R:
        async def resolve(self, field, phrase):
            return resolve_value(field, phrase, depts if field == "department" else [])

    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    node = ResolveFilterValuesNode(_R())

    async def _run(question: str):
        plan = QueryPlanner().build_plan(question, QueryAnalyzer().analyze(question), [], views=[view])
        state = await node.execute(AgentState(question=question, raw_question=question, query_plan=plan))
        return state.query_plan

    brk = await _run("2024 Kardiyoloji haric bolum bazinda randevu sayisi")
    assert brk.excluded_departments == ["Kardiyoloji"]
    # The mis-parsed positive filter is cleared — no contradictory equality.
    assert brk.department_filter is None
    built = DeterministicSQLBuilder().build(brk)
    # Atomic exclusion keeps the split breakdown; the positive containment /
    # atomic-equality on the same value must be gone.
    assert f"{_DEPARTMENT_SPLIT_ALIAS}.value NOT IN (N'Kardiyoloji')" in built.sql
    assert "value = N'Kardiyoloji'" not in built.sql
    assert "LIKE N'%,Kardiyoloji,%'" not in built.sql

    tot = await _run("2024 Radyoloji haric toplam randevu")
    assert tot.excluded_departments == ["Radyoloji"]
    built_tot = DeterministicSQLBuilder().build(tot)
    assert "NOT (" in built_tot.sql and "Radyoloji" in built_tot.sql

    plain = await _run("2024 bolum bazinda randevu sayisi")
    assert plain.excluded_departments == []
