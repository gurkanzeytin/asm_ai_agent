"""Phase 1 full-chain conversational QueryPlan memory regressions.

No LLM or database is used.  Each turn traverses ContextResolver -> AgentState
handoff -> RetrieveContextNode/QueryPlanner -> grounded value resolution ->
ContextManager persistence, which is the production ownership chain.
"""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.context import ContextManager
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.planning.models import QueryPlan
from app.planning.value_resolver import resolve_value
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.services.reporting_service import ReportingService


class _GroundedResolver:
    async def resolve(self, field_name: str, phrase: str):
        candidates = ["E", "K", "D"] if field_name == "gender" else []
        return resolve_value(field_name, phrase, candidates)


class _Chain:
    def __init__(self) -> None:
        self.manager = ContextManager(store=SessionStore())
        prompt_service = AsyncMock()
        prompt_service.retrieve_schema_context.return_value = DatabaseContext(
            tables=[], views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])]
        )
        self.retrieve = RetrieveContextNode(prompt_service)
        self.resolve_filters = ResolveFilterValuesNode(_GroundedResolver())
        self.session_id = "phase-1"

    async def turn(self, question: str) -> tuple[QueryPlan, object, AgentState]:
        resolution = self.manager.resolve(question, self.session_id)
        retained = (
            QueryPlan.model_validate(resolution.retained_query_plan_snapshot)
            if resolution.retained_query_plan_snapshot
            else None
        )
        state = AgentState(
            question=resolution.resolved_question,
            raw_question=question,
            retained_query_plan=retained,
            context_follow_up_detected=resolution.follow_up_detected,
        )
        state = await self.retrieve.execute(state)
        state = await self.resolve_filters.execute(state)
        assert state.query_plan is not None
        assert self.manager.update(
            resolution, self.session_id, query_plan=state.query_plan
        )
        return state.query_plan, resolution, state


def _date(plan: QueryPlan) -> tuple[str, str] | None:
    if not plan.date_filters:
        return None
    value = plan.date_filters[0]
    return value.start_date, value.end_date


@pytest.mark.asyncio
async def test_doctor_count_completed_top_ten_full_chain():
    chain = _Chain()
    first, first_resolution, _ = await chain.turn(
        "2026 Ocak ayında doktorların randevu sayılarını ver."
    )
    assert first_resolution.follow_up_detected is False
    assert first.dimensions == ["DoktorId"]
    assert first.metrics == ["appointment_count"]
    assert _date(first) == ("2026-01-01", "2026-01-31")
    assert (first.ranking, first.order) == ("DESC", "DESC")

    second, second_resolution, second_state = await chain.turn(
        "Sadece gerçekleşenleri göster."
    )
    assert second_resolution.follow_up_detected
    assert second_state.retained_query_plan is not None
    assert not {
        "rows", "query_result", "generated_report", "visualization", "chart"
    } & set(second_state.retained_query_plan.model_dump())
    assert second.dimensions == ["DoktorId"]
    assert second.metrics == ["appointment_count"]
    assert _date(second) == _date(first)
    assert second.extra_filters == ["RandevuDurumu = 'Gerçekleşti'"]

    third, third_resolution, _ = await chain.turn("İlk 10 doktoru al.")
    assert third_resolution.follow_up_detected
    assert third.dimensions == ["DoktorId"]
    assert third.metrics == ["appointment_count"]
    assert third.limit == 10
    assert (third.ranking, third.order) == ("DESC", "DESC")
    assert third.extra_filters == second.extra_filters
    assert _date(third) == _date(first)

    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    assert "TOP (10)" in built.sql
    assert "GROUP BY DoktorId" in built.sql
    assert (
        "RandevuDurumu = N'Gerçekleşti'" in built.sql
        or "RandevuDurumu = 'Gerçekleşti'" in built.sql
    )
    assert "2026-01-01" in built.sql and "2026-01-31" in built.sql
    assert "ORDER BY appointment_count DESC" in built.sql


@pytest.mark.asyncio
async def test_gender_ratio_date_override_branch_split_full_chain():
    chain = _Chain()
    first, _, _ = await chain.turn(
        "Kadın ve erkek hastaların oranını göster."
    )
    assert first.dimensions == ["CinsiyetId"]
    assert first.metrics == ["unique_patient_count"]
    assert first.analysis_type == "ratio"
    assert "female_to_male_ratio" in first.derived_calculations[0]

    second, resolution, _ = await chain.turn("Sadece 2025 yılı için hesapla.")
    assert resolution.follow_up_detected
    assert _date(second) == ("2025-01-01", "2025-12-31")
    assert second.dimensions == first.dimensions
    assert second.metrics == first.metrics
    assert second.derived_calculations == first.derived_calculations

    third, resolution, _ = await chain.turn("Şubelere göre ayır.")
    assert resolution.follow_up_detected
    assert third.dimensions == ["CinsiyetId", "SubeAdi"]
    assert third.metrics == ["unique_patient_count"]
    assert third.analysis_type == "ratio"
    assert _date(third) == _date(second)
    assert third.ranking is None and third.limit is None


@pytest.mark.asyncio
async def test_nationality_top_five_then_female_filter_full_chain():
    chain = _Chain()
    first, _, _ = await chain.turn("Uyruk dağılımını listele.")
    assert first.dimensions == ["Uyruk"]
    assert first.metrics == ["appointment_count"]
    assert first.analysis_type == "distribution"

    second, resolution, _ = await chain.turn("İlk 5 uyruğu al.")
    assert resolution.follow_up_detected
    assert second.dimensions == ["Uyruk"]
    assert second.limit == 5
    assert (second.ranking, second.order) == ("DESC", "DESC")

    third, resolution, _ = await chain.turn("Kadın hastalarla sınırla.")
    assert resolution.follow_up_detected
    assert third.dimensions == ["Uyruk"]
    assert third.metrics == ["appointment_count"]
    assert third.limit == 5 and third.ranking == "DESC"
    assert third.resolved_filters["gender"].grounded
    assert third.resolved_filters["gender"].values == ["K"]

    # The deterministic builder consumes the grounded typed filter through the
    # same canonical rendering path used by status/branch filters.
    built = DeterministicSQLBuilder().build(third)
    assert isinstance(built, DeterministicSQL)
    assert "CinsiyetId = N'K'" in built.sql


@pytest.mark.asyncio
async def test_average_duration_top_ten_departments_full_chain():
    chain = _Chain()
    first, _, _ = await chain.turn(
        "Bölümlere göre ortalama randevu süresini karşılaştır."
    )
    assert first.dimensions == ["GenelRandevuBolumAdi"]
    assert first.metrics == ["appointment_duration_average"]
    assert first.analysis_type == "duration_analysis"

    second, resolution, _ = await chain.turn("En yüksek 10 bölümü göster.")
    assert resolution.follow_up_detected
    assert second.dimensions == first.dimensions
    assert second.metrics == first.metrics
    assert second.analysis_type == "ranking"
    assert second.limit == 10
    assert (second.ranking, second.order) == ("DESC", "DESC")

    built = DeterministicSQLBuilder().build(second)
    assert isinstance(built, DeterministicSQL)
    assert "TOP (10)" in built.sql
    assert "AVG(CAST(RandevuSuresi AS FLOAT)) AS appointment_duration_average" in built.sql
    assert "GROUP BY GenelRandevuBolumAdi" in built.sql
    assert "ORDER BY appointment_duration_average DESC" in built.sql


def test_independent_full_question_receives_no_structured_snapshot():
    manager = ContextManager(store=SessionStore())
    seed = QueryPlan(question="seed", metrics=["appointment_count"], limit=10)
    resolution = manager.resolve("Toplam randevu sayısını göster.", "independent")
    assert manager.update(resolution, "independent", query_plan=seed)

    independent = manager.resolve(
        "Kadın hastaların yaş dağılımını göster.", "independent"
    )
    assert independent.follow_up_detected is False
    assert independent.retained_query_plan_snapshot is None


def test_failed_store_write_is_reported_as_failure():
    class FailingStore(SessionStore):
        def update(self, session_id, mutator):
            raise RuntimeError("write failed")

    manager = ContextManager(store=FailingStore())
    resolution = manager.resolve("Toplam randevu sayısını göster.", "failure")
    assert manager.update(
        resolution,
        "failure",
        query_plan=QueryPlan(question=resolution.resolved_question),
    ) is False


@pytest.mark.asyncio
async def test_reporting_service_does_not_claim_failed_memory_write():
    class FailingContextManager(ContextManager):
        def update(self, *args, **kwargs) -> bool:
            return False

    class SuccessfulGraph:
        async def ainvoke(self, initial_state):
            return {
                "generated_report": GeneratedReport(
                    title="T", markdown="# T", provider="test", model="test", latency_ms=0
                ),
                "outcome": AgentOutcome.EXECUTE_SQL.value,
                "query_result": QueryResult(
                    columns=["appointment_count"],
                    rows=[{"appointment_count": 1}],
                    row_count=1,
                    execution_time_ms=1,
                    success=True,
                    executed_at=datetime.now(),
                    database_provider="mssql",
                ),
                "query_plan": QueryPlan(
                    question="Toplam randevu sayısını göster.",
                    metrics=["appointment_count"],
                ),
            }

    result = await ReportingService(
        SuccessfulGraph(), FailingContextManager(store=SessionStore())
    ).run_workflow("Toplam randevu sayısını göster.", session_id="failure")
    assert result.memory_updated is False


@pytest.mark.asyncio
async def test_reporting_service_hands_retained_plan_to_agent_state():
    manager = ContextManager(store=SessionStore())
    initial_resolution = manager.resolve(
        "2026 Ocak ayında doktorların randevu sayılarını ver.", "handoff"
    )
    prior = QueryPlan(
        question=initial_resolution.resolved_question,
        metrics=["appointment_count"],
        dimensions=["DoktorId"],
        limit=7,
    )
    assert manager.update(initial_resolution, "handoff", query_plan=prior)

    class CaptureGraph:
        state = None

        async def ainvoke(self, initial_state):
            self.state = initial_state
            return {
                "generated_report": GeneratedReport(
                    title="T", markdown="# T", provider="test", model="test", latency_ms=0
                ),
                "outcome": AgentOutcome.OUT_OF_SCOPE.value,
            }

    graph = CaptureGraph()
    await ReportingService(graph, manager).run_workflow(
        "Sadece gerçekleşenleri göster.", session_id="handoff"
    )
    assert graph.state.raw_question == "Sadece gerçekleşenleri göster."
    assert graph.state.context_follow_up_detected is True
    assert graph.state.retained_query_plan == prior
