"""Chat-memory architecture stabilization tests.

Covers: session isolation (never a shared "default" session), the canonical
analysis-type persistence fix (TREND must never be stored as "list"), the
memory write policy (only a successful, data-bearing outcome persists
context), bounded memory (TTL + max turns via settings), reset idempotency,
concurrency safety of SessionStore, and the tightened follow-up detection
(a full independent question must not inherit context merely because it
shares an entity type or contains a generic analytics word).

Deterministic — no LLM, no real database.
"""

import asyncio
from datetime import datetime

import pytest

from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.context import ContextManager
from app.context.analysis_type import CanonicalAnalysisType, resolve_canonical_analysis_type
from app.context.session_store import DEFAULT_SESSION_ID, SessionStore, generate_session_id
from app.services.reporting_service import ReportingService


def make_query_result(row_count: int = 1) -> QueryResult:
    return QueryResult(
        columns=["c"],
        rows=[{"c": 1}] * row_count,
        row_count=row_count,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )


def make_report() -> GeneratedReport:
    return GeneratedReport(title="T", markdown="# T", provider="test", model="m", latency_ms=0.0)


class FakeGraph:
    """Agent graph stub returning a pre-built final state dict."""

    def __init__(self, final_state: dict):
        self.final_state = final_state

    async def ainvoke(self, initial_state):
        return self.final_state


# ─────────────────────────────────────────────
# 1. Session ID contract / isolation
# ─────────────────────────────────────────────


class TestSessionIsolation:
    @pytest.mark.asyncio
    async def test_two_omitted_session_ids_do_not_share_context(self):
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
                "analytics": None,
            }
        )
        service = ReportingService(agent_graph=graph)

        result_a = await service.run_workflow("Bugün kaç randevu oluşturuldu?")
        result_b = await service.run_workflow("Bugün kaç randevu oluşturuldu?")

        assert result_a.session_id != result_b.session_id
        assert result_a.session_id != DEFAULT_SESSION_ID
        assert result_b.session_id != DEFAULT_SESSION_ID

    @pytest.mark.asyncio
    async def test_omitted_session_id_never_falls_back_to_default(self):
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
            }
        )
        service = ReportingService(agent_graph=graph)
        result = await service.run_workflow("Toplam kaç randevu var?")
        assert result.session_id is not None
        assert result.session_id != "default"
        assert result.session_id != DEFAULT_SESSION_ID

    @pytest.mark.asyncio
    async def test_explicit_different_session_ids_do_not_share_context(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="user-a")
        resolution_b = manager.resolve("Doktorları listele", "user-b")

        assert not resolution_b.applied

    @pytest.mark.asyncio
    async def test_explicit_same_session_id_can_share_context(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="user-a")
        resolution = manager.resolve("Doktorları listele", "user-a")

        assert resolution.inherited.get("department") == "Kardiyoloji"

    def test_generate_session_id_is_uuid_based_and_unique(self):
        first = generate_session_id()
        second = generate_session_id()
        assert first != second
        assert "sess-" in first
        # Must never look like a patient/user identifier: pure UUID after prefix.
        import uuid

        uuid.UUID(first.removeprefix("sess-"))

    @pytest.mark.asyncio
    async def test_none_session_id_bypasses_context_engine_entirely(self):
        """Explicit None (benchmarks/eval harness) must still work — distinct from omission."""
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
            }
        )
        service = ReportingService(agent_graph=graph)
        result = await service.run_workflow("Bugün kaç randevu var?", session_id=None)
        assert result.session_id is None
        assert result.memory_updated is False


# ─────────────────────────────────────────────
# 2. Canonical analysis-type persistence (the analysis=list bug)
# ─────────────────────────────────────────────


class TestCanonicalAnalysisType:
    def test_trend_analytics_type_maps_to_trend(self):
        assert (
            resolve_canonical_analysis_type(analytics_type="trend")
            == CanonicalAnalysisType.TREND
        )

    def test_growth_rate_maps_to_trend(self):
        assert (
            resolve_canonical_analysis_type(analytics_type="growth_rate")
            == CanonicalAnalysisType.TREND
        )

    def test_comparison_maps_to_comparison(self):
        assert (
            resolve_canonical_analysis_type(analytics_type="comparison")
            == CanonicalAnalysisType.COMPARISON
        )

    def test_distribution_maps_to_distribution(self):
        assert (
            resolve_canonical_analysis_type(analytics_type="distribution")
            == CanonicalAnalysisType.DISTRIBUTION
        )

    def test_list_maps_to_list(self):
        assert resolve_canonical_analysis_type(analytics_type="list") == CanonicalAnalysisType.LIST

    def test_clarification_outcome_overrides_analytics_type(self):
        result = resolve_canonical_analysis_type(
            analytics_type="trend", outcome="ASK_CLARIFICATION"
        )
        assert result == CanonicalAnalysisType.CLARIFICATION

    def test_out_of_scope_outcome_maps_correctly(self):
        assert (
            resolve_canonical_analysis_type(outcome="OUT_OF_SCOPE")
            == CanonicalAnalysisType.OUT_OF_SCOPE
        )

    def test_nothing_supplied_returns_none(self):
        assert resolve_canonical_analysis_type() is None

    def test_context_manager_persists_canonical_type_not_keyword_guess(self):
        """Root-cause regression: a question whose raw wording lacks trend cue
        words, but whose ACTUAL pipeline result is trend, must persist as
        'trend' — never silently collapse to the keyword-detector's guess."""
        manager = ContextManager()
        # This wording alone would keyword-match nothing definitive (no
        # trend/comparison/ranking/count/list cue) in the extractor.
        resolution = manager.resolve("Son 6 aydaki randevu eğilimini yorumla", "s1")
        manager.update(resolution, "s1", canonical_analysis_type="trend")

        context = manager._store.get("s1")
        assert context.analysis_type == "trend"
        assert context.analysis_type != "list"

    def test_canonical_type_overrides_keyword_guess_even_when_present(self):
        """Even when the raw text WOULD keyword-match something else (e.g. a
        listing verb), the real post-execution result always wins."""
        manager = ContextManager()
        resolution = manager.resolve("Randevu trendini göster ve listele", "s1")
        manager.update(resolution, "s1", canonical_analysis_type="trend")

        context = manager._store.get("s1")
        assert context.analysis_type == "trend"


# ─────────────────────────────────────────────
# 3. Memory write policy
# ─────────────────────────────────────────────


class TestMemoryWritePolicy:
    @pytest.mark.asyncio
    async def test_successful_workflow_updates_memory(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="s1")

        assert result.memory_updated is True
        assert result.memory_turn_count == 1

    @pytest.mark.asyncio
    async def test_errors_present_does_not_update_memory(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
                "errors": ["SQL validation failed: forbidden statement"],
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="s1")

        assert result.memory_updated is False
        assert result.memory_turn_count == 0

    @pytest.mark.asyncio
    async def test_safe_error_outcome_does_not_update_memory(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        # No generated_report -> ReportingService synthesizes SAFE_ERROR itself.
        graph = FakeGraph({"errors": ["GenerateSQLNode failed: LLM timeout"]})
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="s1")

        assert result.outcome == AgentOutcome.SAFE_ERROR.value
        assert result.memory_updated is False

    @pytest.mark.asyncio
    async def test_out_of_scope_does_not_update_memory(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.OUT_OF_SCOPE.value,
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow("Bugün hava nasıl?", session_id="s1")

        assert result.memory_updated is False

    @pytest.mark.asyncio
    async def test_no_query_result_does_not_update_memory(self):
        """An EXECUTE_SQL-tagged state without an actual query_result (invalid
        result shape) must not be treated as a persistable success."""
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": None,
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="s1")

        assert result.memory_updated is False

    @pytest.mark.asyncio
    async def test_no_result_guidance_still_updates_memory(self):
        """A genuinely executed query that legitimately returned zero rows is
        not a failure — its filters should still be available to follow-ups."""
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.NO_RESULT_GUIDANCE.value,
                "query_result": make_query_result(row_count=0),
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="s1")

        assert result.memory_updated is True

    @pytest.mark.asyncio
    async def test_unresolved_clarification_does_not_overwrite_valid_context(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        # Turn 1: establishes valid department context.
        await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="s1")
        before = manager._store.get("s1").department
        assert before == "Kardiyoloji"

        # Turn 2: an ambiguous pronoun with no context anchor -> clarification.
        graph.final_state = {
            "generated_report": make_report(),
            "outcome": AgentOutcome.ASK_CLARIFICATION.value,
        }
        result = await service.run_workflow("O doktorun randevularını göster", session_id="s1")

        assert result.memory_updated is False
        after = manager._store.get("s1").department
        assert after == "Kardiyoloji"  # untouched, not overwritten with incomplete data

    @pytest.mark.asyncio
    async def test_invalid_result_shape_does_not_update_memory_and_preserves_prior_context(self):
        """SAFE_ERROR from a blocked result shape (missing/renamed expected
        columns) must never persist the failed turn's analytical state, and
        must not clobber a previously valid session's context."""
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        # Turn 1: establishes valid department context.
        await service.run_workflow("Kardiyoloji doktorlarını göster", session_id="s1")
        assert manager._store.get("s1").department == "Kardiyoloji"

        # Turn 2: the pipeline detected a result-shape mismatch and produced
        # the deterministic safe-clarification report with SAFE_ERROR.
        graph.final_state = {
            "generated_report": make_report(),
            "outcome": AgentOutcome.SAFE_ERROR.value,
            "query_result": make_query_result(),
            "analytics_blocked_reason": "missing expected columns: appointment_count",
        }
        result = await service.run_workflow(
            "Şubelere göre randevu sayısını göster", session_id="s1"
        )

        assert result.memory_updated is False
        assert manager._store.get("s1").department == "Kardiyoloji"

    @pytest.mark.asyncio
    async def test_valid_grouped_multi_metric_result_updates_memory(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow(
            "Şubelere göre randevu sayısı ve gerçekleşme oranını karşılaştır",
            session_id="s1",
        )

        assert result.memory_updated is True

    @pytest.mark.asyncio
    async def test_insufficient_complete_periods_trend_still_updates_memory(self):
        """A successful trend query that simply lacks enough complete periods
        for a trend verdict (INSUFFICIENT_COMPLETE_PERIODS) is not an error —
        the SQL executed correctly and produced a valid resolved dimension/
        metric context for follow-up turns. No trend-verdict field is ever
        persisted to session context (see ContextManager.update), so this
        must not be blocked."""
        store = SessionStore()
        manager = ContextManager(store=store)
        from app.analytics.models import AnalyticsResult, DataShape
        from app.analytics.trend_analysis import TrendMetrics

        analytics = AnalyticsResult(
            analytics_type="trend",
            data_shape=DataShape.TIME_SERIES,
            metrics={"count": 1, "total": 5.0},
            row_count=1,
            trend_metrics=TrendMetrics(
                trend_consistency="insufficient_data", comparable_period_count=0
            ),
        )
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
                "analytics": analytics,
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow(
            "Son 6 aydaki randevu eğilimini kısaca yorumla.", session_id="s1"
        )

        assert result.memory_updated is True

    @pytest.mark.asyncio
    async def test_comparison_insufficient_but_valid_result_updates_memory(self):
        """A valid one-category grouped result (comparison_sufficient=False)
        is still a successful, data-bearing turn — it must remain a valid
        memory-persisting turn, per spec."""
        store = SessionStore()
        manager = ContextManager(store=store)
        from app.analytics.models import AnalyticsResult, DataShape

        analytics = AnalyticsResult(
            analytics_type="comparison",
            data_shape=DataShape.CATEGORICAL,
            metrics={"count": 1, "total": 89.0},
            row_count=1,
            comparison_category_count=1,
            comparison_sufficient=False,
            comparison_limitation_reason="Seçilen kapsamda yalnızca bir kategori bulundu.",
        )
        graph = FakeGraph(
            {
                "generated_report": make_report(),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": make_query_result(),
                "analytics": analytics,
            }
        )
        service = ReportingService(agent_graph=graph, context_manager=manager)

        result = await service.run_workflow(
            "Şubelere göre randevu sayısını karşılaştır", session_id="s1"
        )

        assert result.memory_updated is True


# ─────────────────────────────────────────────
# 4. Bounded memory (settings-driven)
# ─────────────────────────────────────────────


class TestBoundedMemory:
    def test_max_turns_enforced(self):
        store = SessionStore(max_turns=3)
        manager = ContextManager(store=store)
        for index in range(10):
            resolution = manager.resolve(f"Bugün kaç randevu var? ({index})", "s1")
            manager.update(resolution, "s1")
        context = store.get("s1")
        assert len(context.turns) == 3

    def test_ttl_expiry_works(self):
        class FakeClock:
            def __init__(self):
                self.now = 0.0

            def __call__(self):
                return self.now

        clock = FakeClock()
        store = SessionStore(ttl_seconds=60.0, now_fn=clock)
        manager = ContextManager(store=store)
        resolution = manager.resolve("Kardiyoloji doktorlarını göster", "s1")
        manager.update(resolution, "s1")

        clock.now += 61.0
        assert store.is_expired_or_absent("s1")
        resolution2 = manager.resolve("Doktorları listele", "s1")
        assert not resolution2.applied

    def test_settings_defaults_are_wired(self):
        from app.core.config import settings

        assert settings.CHAT_MEMORY_MAX_TURNS > 0
        assert settings.CHAT_MEMORY_TTL_SECONDS > 0


# ─────────────────────────────────────────────
# 5. Reset support
# ─────────────────────────────────────────────


class TestMemoryReset:
    def test_reset_clears_one_session_only(self):
        store = SessionStore()
        manager = ContextManager(store=store)
        r1 = manager.resolve("Kardiyoloji doktorlarını göster", "a")
        manager.update(r1, "a")
        r2 = manager.resolve("Psikiyatri doktorlarını göster", "b")
        manager.update(r2, "b")

        manager.clear("a")

        assert manager._store.get("a").department is None
        assert manager._store.get("b").department == "Psikiyatri"

    def test_reset_missing_session_is_idempotent(self):
        manager = ContextManager()
        first = manager.clear("never-existed")
        second = manager.clear("never-existed")
        assert first is False
        assert second is False

    def test_reset_existing_session_returns_true_once(self):
        manager = ContextManager()
        r = manager.resolve("Kardiyoloji doktorlarını göster", "s1")
        manager.update(r, "s1")
        assert manager.clear("s1") is True
        assert manager.clear("s1") is False  # already gone -> idempotent False


# ─────────────────────────────────────────────
# 6. Concurrency safety
# ─────────────────────────────────────────────


class TestConcurrencySafety:
    @pytest.mark.asyncio
    async def test_concurrent_same_session_updates_do_not_lose_turns(self):
        store = SessionStore(max_turns=100)
        manager = ContextManager(store=store)

        async def do_update(index: int) -> None:
            resolution = manager.resolve(f"Bugün kaç randevu var? ({index})", "s1")
            manager.update(resolution, "s1")

        await asyncio.gather(*(do_update(i) for i in range(20)))

        context = store.get("s1")
        assert len(context.turns) == 20

    def test_atomic_update_mutator_sees_live_context(self):
        store = SessionStore()
        seen_ids = []

        def mutator(context):
            seen_ids.append(context.session_id)
            context.department = "Kardiyoloji"

        result = store.update("s1", mutator)
        assert seen_ids == ["s1"]
        assert result.department == "Kardiyoloji"
        assert store.get("s1").department == "Kardiyoloji"

    @pytest.mark.asyncio
    async def test_different_sessions_do_not_block_each_other_incorrectly(self):
        store = SessionStore()
        manager = ContextManager(store=store)

        async def do_update(session: str) -> None:
            resolution = manager.resolve("Kardiyoloji doktorlarını göster", session)
            manager.update(resolution, session)

        await asyncio.gather(*(do_update(f"s{i}") for i in range(10)))

        for i in range(10):
            assert store.get(f"s{i}").department == "Kardiyoloji"


# ─────────────────────────────────────────────
# 7. Live-scenario-style follow-up detection (tightened inheritance)
# ─────────────────────────────────────────────


class TestFollowUpDetectionScenarios:
    def test_scenario_b_genuine_followup_inherits_and_overrides_date(self):
        manager = ContextManager()
        r1 = manager.resolve(
            "Son 6 ayda şubelere göre randevu sayılarını karşılaştır", "s1"
        )
        manager.update(r1, "s1")

        r2 = manager.resolve("Peki geçen ay?", "s1")

        assert r2.context_applied is True
        assert r2.follow_up_detected is True
        assert "gecen ay" in r2.resolved_question
        assert "karsilastir" in r2.resolved_question

    def test_scenario_d_unrelated_full_question_does_not_inherit(self):
        manager = ContextManager()
        r1 = manager.resolve("Kardiyoloji doktorlarını göster", "s1")
        manager.update(r1, "s1")

        r2 = manager.resolve("Kadın hastaların yaş dağılımını göster", "s1")

        assert r2.context_applied is False
        assert "department" not in r2.inherited

    def test_same_entity_type_alone_does_not_imply_followup(self):
        """A full, independent question mentioning the same entity type as a
        previous turn must not be treated as a follow-up merely for that."""
        manager = ContextManager()
        r1 = manager.resolve("Kardiyoloji doktorlarını göster", "s1")
        manager.update(r1, "s1")

        r2 = manager.resolve("Üroloji bölümündeki doktorların listesini çıkar", "s1")

        # Explicit department in the new question — never inherits Kardiyoloji.
        assert "department" not in r2.inherited

    def test_independent_full_question_does_not_inherit(self):
        manager = ContextManager()
        r1 = manager.resolve("Beklemede olan randevuları getir", "s1")
        manager.update(r1, "s1")

        r2 = manager.resolve(
            "Son bir yılda gerçekleştirilen tüm ameliyatların listesini çıkar", "s1"
        )

        assert r2.context_applied is False

    def test_short_elliptical_department_followup_still_works(self):
        """'Doktor bazında?' style short follow-ups must keep working — the
        tightened gate restricts to short/elliptical questions, it does not
        remove department inheritance altogether."""
        manager = ContextManager()
        r1 = manager.resolve("Kardiyoloji doktorlarını göster", "s1")
        manager.update(r1, "s1")

        r2 = manager.resolve("Kaç hasta muayene edildi?", "s1")

        assert r2.inherited.get("department") == "Kardiyoloji"
        assert r2.follow_up_detected is True
        assert "elliptical_department_inherit" in r2.follow_up_signals
