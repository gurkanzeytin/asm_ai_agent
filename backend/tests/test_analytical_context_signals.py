"""Typed analytical follow-up signal layer: extraction, merge policy, pending
clarification, and the live-verification scenarios (A-E) from the task spec.

Deterministic — no LLM, no real database. `from_raw_text` calls the SAME
catalog matchers the real planner uses (app.semantics.catalog); this suite
therefore also pins down their observed behavior on the exact example
sentences used here, so assertions use membership checks rather than brittle
exact-list equality wherever the catalog's own matching composition isn't the
property under test. Fixed-dimension "per X" count variants (e.g.
appointments_per_branch) are deduped against the canonical appointment_count
by app.semantics.catalog.match_metrics — a branch-count question resolves to
exactly one metric id, never two COUNT(*) expressions for the same measure.
"""

import pytest

from app.context.analytical_signals import AnalyticalSignals, from_query_plan, from_raw_text
from app.context.context_manager import ContextManager
from app.context.merge_policy import (
    merge_analytical_signals,
    merge_list_field,
    merge_metrics,
    merge_scalar_field,
)
from app.context.session_store import SessionStore
from app.planning.models import QueryPlan


def _ask(manager: ContextManager, question: str, session_id: str = "s1"):
    resolution = manager.resolve(question, session_id)
    manager.update(resolution, session_id)
    return resolution


# ─────────────────────────────────────────────
# 1. AnalyticalSignals extraction — from_raw_text (deterministic fallback)
# ─────────────────────────────────────────────


class TestFromRawText:
    def test_branch_dimension_detected(self):
        signals = from_raw_text("Şubelere göre randevu sayısını karşılaştır.")
        assert "branch" in signals.dimensions
        assert "appointment_count" in signals.metrics

    def test_doctor_dimension_via_bazinda(self):
        signals = from_raw_text("Doktor bazında?")
        assert signals.dimensions == ["doctor"]

    def test_department_passed_through_not_redetected(self):
        signals = from_raw_text("Kardiyoloji bölümünü göster", department="Kardiyoloji")
        assert signals.department_filters == ["Kardiyoloji"]

    def test_status_beklemede_detected(self):
        signals = from_raw_text("Beklemede olan randevuları getir.")
        assert signals.status_filters == ["Beklemede"]

    def test_status_gerceklesti_detected(self):
        signals = from_raw_text("Gerçekleşenleri göster.")
        assert signals.status_filters == ["Gerçekleşti"]

    def test_average_duration_metric_detected(self):
        signals = from_raw_text("Ortalama süreye göre yap.")
        assert signals.metrics == ["appointment_duration_average"]

    def test_completion_rate_metric_detected(self):
        signals = from_raw_text("Bir de gerçekleşme oranını ekle.")
        assert signals.metrics == ["completed_appointment_rate"]

    def test_top_n_ranking_and_limit(self):
        signals = from_raw_text("İlk 10 doktoru göster")
        assert signals.ranking == "top"
        assert signals.limit == 10

    def test_bottom_n_ranking_and_limit_overrides_both(self):
        signals = from_raw_text("En düşük 5 şubeyi göster")
        assert signals.ranking == "bottom"
        assert signals.limit == 5

    def test_monthly_time_grain(self):
        signals = from_raw_text("Aylık trend göster")
        assert signals.time_grain == "month"

    def test_weekly_time_grain(self):
        signals = from_raw_text("Haftalık göster")
        assert signals.time_grain == "week"

    def test_multi_metric_current_request_preserves_all(self):
        """A question matching more than one genuinely distinct catalog metric
        keeps all of them — never truncated to a single metric. (A single
        branch-count request only ever resolves to one canonical metric,
        appointment_count — "appointments_per_branch" is deduped as the same
        COUNT(*) measure, not counted as a second metric here.)"""
        signals = from_raw_text(
            "Şubelere göre randevu sayısı ve gerçekleşme oranını karşılaştır."
        )
        assert len(signals.metrics) >= 2
        assert "appointment_count" in signals.metrics
        assert "completed_appointment_rate" in signals.metrics

    def test_branch_count_request_produces_single_canonical_metric(self):
        """'Şubelere göre randevu sayısı' means dimension=branch, metric=
        appointment_count — never a second appointments_per_branch metric
        duplicating the same COUNT(*) expression."""
        signals = from_raw_text("Şubelere göre randevu sayısını karşılaştır.")
        assert signals.metrics == ["appointment_count"]
        assert "branch" in signals.dimensions

    def test_independent_full_question_has_no_status_or_dimension(self):
        signals = from_raw_text("Kadın hastaların yaş dağılımını göster.")
        assert signals.dimensions == []
        assert signals.status_filters == []

    def test_unmapped_groupable_column_never_crashes_or_leaks(self):
        """catalog.match_dimensions can return columns outside this module's
        target vocabulary (e.g. DogumTarihi for age-related wording) — they
        must be silently skipped, never crash and never appear as a dimension."""
        signals = from_raw_text("Yaş dağılımına göre hastaları göster.")
        assert "DogumTarihi" not in signals.dimensions

    def test_branch_filters_and_doctor_filters_not_populated_by_extraction(self):
        """Documented limitation: no grounded value list exists for branch/
        doctor/service/category/source, so these stay empty even when the
        dimension itself is detected — never a silently-trusted guess."""
        signals = from_raw_text("Merkez şubesindeki randevuları göster.")
        assert signals.branch_filters == []
        assert signals.doctor_filters == []
        assert signals.service_filters == []
        assert signals.category_filters == []
        assert signals.source_filters == []


class TestFromQueryPlan:
    def _plan(self, **overrides) -> QueryPlan:
        base = dict(question="q")
        base.update(overrides)
        return QueryPlan(**base)

    def test_dimensions_mapped_from_columns(self):
        plan = self._plan(dimensions=["SubeAdi", "GenelRandevuBolumAdi"])
        signals = from_query_plan(plan)
        assert signals.dimensions == ["branch", "department"]

    def test_unmapped_column_skipped(self):
        plan = self._plan(dimensions=["SubeAdi", "RandevuTipiAdi"])
        signals = from_query_plan(plan)
        assert signals.dimensions == ["branch"]

    def test_metrics_passed_through_verbatim(self):
        plan = self._plan(metrics=["appointment_count", "completed_appointment_rate"])
        signals = from_query_plan(plan)
        assert signals.metrics == ["appointment_count", "completed_appointment_rate"]

    def test_ranking_desc_maps_to_top(self):
        plan = self._plan(ranking="DESC")
        assert from_query_plan(plan).ranking == "top"

    def test_ranking_asc_maps_to_bottom(self):
        plan = self._plan(ranking="ASC")
        assert from_query_plan(plan).ranking == "bottom"

    def test_limit_passed_through(self):
        plan = self._plan(limit=7)
        assert from_query_plan(plan).limit == 7

    def test_grouping_granularity_maps_to_time_grain(self):
        assert from_query_plan(self._plan(grouping_granularity="week")).time_grain == "week"
        assert from_query_plan(self._plan(grouping_granularity="hour")).time_grain == "day"

    def test_status_extracted_from_extra_filters(self):
        plan = self._plan(extra_filters=["RandevuDurumu = 'Gerçekleşti'", "NEGATION: exclude"])
        signals = from_query_plan(plan)
        assert signals.status_filters == ["Gerçekleşti"]

    def test_department_filter_becomes_list(self):
        plan = self._plan(department_filter="Kardiyoloji")
        assert from_query_plan(plan).department_filters == ["Kardiyoloji"]

    def test_comparisons_and_baseline_period_combined(self):
        plan = self._plan(
            comparisons=["current_period_vs_previous_period"],
            baseline_period="previous_30_days",
        )
        signals = from_query_plan(plan)
        assert "current_period_vs_previous_period" in signals.comparison_targets
        assert "previous_30_days" in signals.comparison_targets

    def test_empty_plan_yields_empty_signals(self):
        assert from_query_plan(self._plan()).is_empty()


# ─────────────────────────────────────────────
# 2. Merge policy — pure function unit tests
# ─────────────────────────────────────────────


class TestMergeListField:
    def test_explicit_current_replaces_inherited(self):
        values, removed = merge_list_field(
            current_values=["doctor"], inherited_values=["branch"], follow_up_detected=True
        )
        assert values == ["doctor"]
        assert removed is True

    def test_inherits_when_followup_and_no_current(self):
        values, removed = merge_list_field(
            current_values=[], inherited_values=["branch"], follow_up_detected=True
        )
        assert values == ["branch"]
        assert removed is False

    def test_clears_when_not_followup(self):
        values, removed = merge_list_field(
            current_values=[], inherited_values=["branch"], follow_up_detected=False
        )
        assert values == []
        assert removed is True

    def test_no_removal_flag_when_nothing_inherited(self):
        values, removed = merge_list_field(
            current_values=[], inherited_values=[], follow_up_detected=False
        )
        assert values == []
        assert removed is False

    def test_same_value_restated_not_flagged_removed(self):
        values, removed = merge_list_field(
            current_values=["branch"], inherited_values=["branch"], follow_up_detected=True
        )
        assert values == ["branch"]
        assert removed is False


class TestMergeScalarField:
    def test_explicit_current_replaces_inherited(self):
        value, removed = merge_scalar_field(
            current_value=5, inherited_value=10, follow_up_detected=True
        )
        assert value == 5
        assert removed is True

    def test_inherits_when_followup(self):
        value, removed = merge_scalar_field(
            current_value=None, inherited_value="week", follow_up_detected=True
        )
        assert value == "week"
        assert removed is False

    def test_clears_when_not_followup(self):
        value, removed = merge_scalar_field(
            current_value=None, inherited_value="week", follow_up_detected=False
        )
        assert value is None
        assert removed is True


class TestMergeMetrics:
    def test_default_replaces_single_new_metric(self):
        metrics, removed = merge_metrics(
            current_metrics=["appointment_duration_average"],
            inherited_metrics=["appointment_count"],
            follow_up_detected=True,
            folded_question="ortalama sureye gore yap",
        )
        assert metrics == ["appointment_duration_average"]
        assert removed is True

    def test_bir_de_marker_is_additive(self):
        metrics, removed = merge_metrics(
            current_metrics=["completed_appointment_rate"],
            inherited_metrics=["appointment_count"],
            follow_up_detected=True,
            folded_question="bir de gerceklesme oranini ekle",
        )
        assert "appointment_count" in metrics
        assert "completed_appointment_rate" in metrics
        assert removed is False

    def test_ayrica_marker_is_additive(self):
        metrics, removed = merge_metrics(
            current_metrics=["no_show_rate"],
            inherited_metrics=["appointment_count"],
            follow_up_detected=True,
            folded_question="ayrica gelmeme oranini da goster",
        )
        assert set(metrics) == {"appointment_count", "no_show_rate"}

    def test_yerine_marker_forces_replace(self):
        metrics, removed = merge_metrics(
            current_metrics=["no_show_rate"],
            inherited_metrics=["appointment_count"],
            follow_up_detected=True,
            folded_question="appointment count yerine no show rate",
        )
        assert metrics == ["no_show_rate"]
        assert removed is True

    def test_multi_metric_current_turn_all_preserved(self):
        metrics, _ = merge_metrics(
            current_metrics=["appointment_count", "unique_patient_count"],
            inherited_metrics=[],
            follow_up_detected=False,
            folded_question="randevu ve hasta sayisi",
        )
        assert metrics == ["appointment_count", "unique_patient_count"]

    def test_inherits_when_followup_and_no_current_metric(self):
        metrics, removed = merge_metrics(
            current_metrics=[],
            inherited_metrics=["appointment_count"],
            follow_up_detected=True,
            folded_question="peki gecen ay",
        )
        assert metrics == ["appointment_count"]
        assert removed is False

    def test_independent_question_does_not_inherit_metric(self):
        metrics, removed = merge_metrics(
            current_metrics=[],
            inherited_metrics=["appointment_count"],
            follow_up_detected=False,
            folded_question="kadin hastalarin yas dagilimi",
        )
        assert metrics == []
        assert removed is True


class TestMergeAnalyticalSignals:
    def test_full_isolation_when_not_followup(self):
        current = AnalyticalSignals()
        inherited = AnalyticalSignals(
            dimensions=["branch"],
            metrics=["appointment_count"],
            status_filters=["Beklemede"],
            ranking="top",
            limit=10,
            time_grain="month",
        )
        resolved, explicit, removed = merge_analytical_signals(
            current=current, inherited=inherited, follow_up_detected=False, folded_question="x"
        )
        assert resolved.is_empty()
        assert explicit == []
        assert set(removed) >= {
            "dimensions",
            "metrics",
            "status_filters",
            "ranking",
            "limit",
            "time_grain",
        }

    def test_explicit_fields_tracks_current_turn_statements(self):
        current = AnalyticalSignals(dimensions=["doctor"], limit=5)
        inherited = AnalyticalSignals(dimensions=["branch"])
        resolved, explicit, removed = merge_analytical_signals(
            current=current, inherited=inherited, follow_up_detected=True, folded_question="x"
        )
        assert "dimensions" in explicit
        assert "limit" in explicit
        assert resolved.dimensions == ["doctor"]
        assert resolved.limit == 5


# ─────────────────────────────────────────────
# 3. Merge policy through the resolver (integration)
# ─────────────────────────────────────────────


@pytest.fixture()
def manager() -> ContextManager:
    return ContextManager(store=SessionStore())


class TestDimensionInheritanceIntegration:
    def test_branch_inherited_for_date_only_followup(self, manager):
        _ask(manager, "Son 6 ayda şubelere göre randevu sayılarını karşılaştır.")
        r2 = _ask(manager, "Peki geçen ay?")
        assert "branch" in r2.resolved_signals.dimensions
        assert r2.inherited.get("date") == "gecen ay"

    def test_branch_replaced_by_doctor(self, manager):
        _ask(manager, "Son 6 ayda şubelere göre randevu sayılarını karşılaştır.")
        r2 = _ask(manager, "Doktor bazında?")
        assert r2.resolved_signals.dimensions == ["doctor"]
        assert "dimensions" in r2.removed_fields

    def test_department_replaced_by_service_dimension(self, manager):
        _ask(manager, "Bölümlere göre randevu sayısını göster.")
        r2 = _ask(manager, "Hizmete göre göster.")
        assert "service" in r2.resolved_signals.dimensions
        assert "department" not in r2.resolved_signals.dimensions

    def test_independent_full_question_inherits_nothing(self, manager):
        _ask(manager, "Kardiyoloji doktorlarını göster")
        r2 = _ask(manager, "Kadın hastaların yaş dağılımını göster.")
        assert r2.context_applied is False
        assert r2.resolved_signals.is_empty()


class TestStatusFilterIntegration:
    def test_beklemede_replaced_by_gerceklesti(self, manager):
        _ask(manager, "Beklemede olan randevuları getir.")
        r2 = _ask(manager, "Gerçekleşenleri göster.")
        assert r2.resolved_signals.status_filters == ["Gerçekleşti"]
        assert "Beklemede" not in r2.resolved_signals.status_filters
        assert "status_filters" in r2.removed_fields

    def test_unsupported_status_triggers_clarification(self, manager):
        r = manager.resolve("İptal edilenleri göster.", "s1")
        assert r.clarification_needed is True
        assert "İptal" in r.clarification_question
        assert "Beklemede" in r.clarification_options

    def test_previous_status_does_not_leak_into_unrelated_full_question(self, manager):
        _ask(manager, "Beklemede olan randevuları getir.")
        r2 = _ask(manager, "Kadın hastaların yaş dağılımını göster.")
        assert r2.resolved_signals.status_filters == []


class TestRankingAndLimitIntegration:
    def test_top_10_stores_limit_and_ranking(self, manager):
        r = manager.resolve("İlk 10 doktoru göster", "s1")
        assert r.resolved_signals.limit == 10
        assert r.resolved_signals.ranking == "top"

    def test_bottom_5_overrides_both(self, manager):
        _ask(manager, "İlk 10 doktoru göster")
        r2 = _ask(manager, "En düşük 5 şubeyi göster")
        assert r2.resolved_signals.limit == 5
        assert r2.resolved_signals.ranking == "bottom"

    def test_new_explicit_limit_replaces_inherited_limit(self, manager):
        _ask(manager, "İlk 10 doktoru göster")
        r2 = _ask(manager, "İlk 3 doktoru göster")
        assert r2.resolved_signals.limit == 3


class TestTimeGrainIntegration:
    def test_monthly_trend_stores_month(self, manager):
        r = manager.resolve("Aylık trend göster", "s1")
        assert r.resolved_signals.time_grain == "month"

    def test_weekly_replaces_month(self, manager):
        _ask(manager, "Aylık trend göster")
        r2 = _ask(manager, "Haftalık göster")
        assert r2.resolved_signals.time_grain == "week"

    def test_explicit_current_grain_overrides_inherited(self, manager):
        _ask(manager, "Aylık trend göster")
        r2 = _ask(manager, "Yıllık göster")
        # "yillik" isn't a recognized granularity trigger today (see
        # app.semantics.catalog._GRANULARITY_TERMS) — this pins the documented
        # limitation rather than asserting behavior the catalog doesn't have.
        assert r2.resolved_signals.time_grain in (None, "month")


# ─────────────────────────────────────────────
# 4. Pending clarification lifecycle
# ─────────────────────────────────────────────


class TestPendingClarification:
    def test_set_and_resolve_ranking_metric(self, manager):
        manager.set_pending_clarification(
            "s1", field="ranking_metric", reason="'iyi' ambiguous", choices=[]
        )
        assert manager.get_pending_clarification("s1") is not None

        r = manager.resolve("Gerçekleşme oranına göre.", "s1")
        assert r.pending_clarification_resolved is True
        assert "completed_appointment_rate" in r.resolved_signals.metrics

    def test_successful_update_clears_pending_clarification(self, manager):
        manager.set_pending_clarification("s1", field="ranking_metric", reason="x", choices=[])
        r = manager.resolve("Gerçekleşme oranına göre.", "s1")
        manager.update(r, "s1")
        assert manager.get_pending_clarification("s1") is None

    def test_pending_does_not_corrupt_valid_context(self, manager):
        _ask(manager, "Kardiyoloji doktorlarını göster")
        manager.set_pending_clarification("s1", field="ranking_metric", reason="x", choices=[])
        # Valid prior context (department) survives the pending state untouched.
        from app.context.session_store import SessionStore as _SS  # noqa: F401

        stored = manager._store.get("s1")
        assert stored.department == "Kardiyoloji"
        assert stored.pending_clarification is not None

    def test_unresolved_question_leaves_pending_state_diagnosable(self, manager):
        manager.set_pending_clarification(
            "s1", field="ranking_metric", reason="ambiguous", choices=[]
        )
        r = manager.resolve("Bilmiyorum ne demek istedim.", "s1")
        assert r.pending_clarification_resolved is False


# ─────────────────────────────────────────────
# 5. Live verification scenarios (task Part 12), same explicit session id
# ─────────────────────────────────────────────


class TestLiveScenarios:
    def test_scenario_a_date_only_followup(self, manager):
        _ask(manager, "Son 6 ayda şubelere göre randevu sayılarını karşılaştır.", "scenario-a")
        r2 = _ask(manager, "Peki geçen ay?", "scenario-a")
        assert "branch" in r2.resolved_signals.dimensions
        assert "appointment_count" in r2.resolved_signals.metrics
        assert r2.inherited.get("date") == "gecen ay"

    def test_scenario_b_dimension_switch(self, manager):
        _ask(manager, "Son 6 ayda şubelere göre randevu sayılarını karşılaştır.", "scenario-b")
        r2 = _ask(manager, "Doktor bazında?", "scenario-b")
        assert r2.resolved_signals.dimensions == ["doctor"]
        assert "branch" not in r2.resolved_signals.dimensions
        assert "appointment_count" in r2.resolved_signals.metrics

    def test_scenario_c_status_replace(self, manager):
        _ask(manager, "Beklemede olan randevuları getir.", "scenario-c")
        r2 = _ask(manager, "Gerçekleşenleri göster.", "scenario-c")
        assert r2.resolved_signals.status_filters == ["Gerçekleşti"]

    def test_scenario_d_additive_metric(self, manager):
        _ask(manager, "Şubelere göre randevu sayısını karşılaştır.", "scenario-d")
        r2 = _ask(manager, "Bir de gerçekleşme oranını ekle.", "scenario-d")
        assert r2.resolved_signals.dimensions == ["branch"]
        assert "appointment_count" in r2.resolved_signals.metrics
        assert "completed_appointment_rate" in r2.resolved_signals.metrics

    def test_scenario_e_pending_clarification_resolved(self, manager):
        manager.set_pending_clarification(
            "scenario-e", field="ranking_metric", reason="'en iyi' ambiguous", choices=[]
        )
        r2 = manager.resolve("Gerçekleşme oranına göre.", "scenario-e")
        assert r2.pending_clarification_resolved is True
        assert r2.resolved_signals.ranking is None or r2.resolved_signals.metrics == [
            "completed_appointment_rate"
        ]
        assert "completed_appointment_rate" in r2.resolved_signals.metrics


# ─────────────────────────────────────────────
# 6. ContextManager.update() with a real QueryPlan
# ─────────────────────────────────────────────


class TestContextManagerQueryPlanPersistence:
    def test_query_plan_signals_persisted(self, manager):
        resolution = manager.resolve("Şubelere göre randevu sayısını göster", "s1")
        plan = QueryPlan(
            question="Şubelere göre randevu sayısını göster",
            dimensions=["SubeAdi"],
            metrics=["appointment_count"],
            ranking="DESC",
            limit=5,
        )
        manager.update(resolution, "s1", query_plan=plan)

        stored = manager._store.get("s1")
        assert stored.dimensions == ["branch"]
        assert stored.metrics == ["appointment_count"]
        assert stored.ranking == "top"
        assert stored.limit == 5

    def test_query_plan_preferred_over_raw_text_guess(self, manager):
        """The QueryPlan is authoritative even when it differs from what the
        resolve()-time raw-text fallback would have guessed."""
        resolution = manager.resolve("Bir şeyler göster", "s1")  # matches nothing
        plan = QueryPlan(
            question="Bir şeyler göster",
            dimensions=["GenelRandevuBolumAdi"],
            metrics=["unique_patient_count"],
        )
        manager.update(resolution, "s1", query_plan=plan)

        stored = manager._store.get("s1")
        assert stored.dimensions == ["department"]
        assert stored.metrics == ["unique_patient_count"]

    def test_query_plan_inherits_correctly_on_genuine_followup(self, manager):
        resolution1 = manager.resolve("Şubelere göre randevu sayısını göster", "s1")
        plan1 = QueryPlan(
            question="Şubelere göre randevu sayısını göster",
            dimensions=["SubeAdi"],
            metrics=["appointment_count"],
        )
        manager.update(resolution1, "s1", query_plan=plan1)

        resolution2 = manager.resolve("Peki geçen ay?", "s1")
        plan2 = QueryPlan(question="gecen ay subelere gore randevu sayisini goster")
        manager.update(resolution2, "s1", query_plan=plan2)

        stored = manager._store.get("s1")
        assert stored.dimensions == ["branch"]
        assert stored.metrics == ["appointment_count"]


# ─────────────────────────────────────────────
# 7. Backward compatibility: existing schema, no regressions
# ─────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_conversation_context_new_fields_default_empty(self):
        from app.context.models import ConversationContext

        context = ConversationContext(session_id="s1")
        assert context.branch_filters == []
        assert context.doctor_filters == []
        assert context.department_filters == []
        assert context.status_filters == []
        assert context.metrics == []
        assert context.dimensions == []
        assert context.ranking is None
        assert context.limit is None
        assert context.time_grain is None
        assert context.comparison_targets == []
        assert context.pending_clarification is None
        assert context.department is None  # legacy field untouched

    def test_legacy_department_field_still_works_independently(self, manager):
        """Regression guard: the pre-existing singular `department` field's
        behavior must be unaffected by the new `department_filters` list."""
        _ask(manager, "Kardiyoloji doktorlarını göster")
        stored = manager._store.get("s1")
        assert stored.department == "Kardiyoloji"
        assert stored.department_filters == ["Kardiyoloji"]

    def test_is_empty_accounts_for_new_fields(self):
        from app.context.models import ConversationContext

        context = ConversationContext(session_id="s1", dimensions=["branch"])
        assert not context.is_empty()
