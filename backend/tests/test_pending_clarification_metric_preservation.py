"""Regression test for a real live multi-turn bug (2026-07-24):

Turn 1: "Kaç tane farklı doktor 2025'te randevu almış" -> unique_doctor_count,
        a SUCCESSFUL answer, persisted to session memory.
Turn 2: "Cerrahi bölümünde 2025'te kaç randevu var" -> "Cerrahi" is ambiguous
        (matches several *Cerrahi departments) -> ASK_CLARIFICATION. This
        outcome is NOT data-bearing, so session memory is never updated with
        turn 2's own (appointment_count) plan - only a bounded
        `pending_clarification` snapshot is stored, per app.context.
        context_manager.set_pending_clarification.
Turn 3: "Genel Cerrahi'yi kastettim" answers the clarification. Before the
        fix, RetrieveContextNode always planned from `state.raw_question`
        (correct for a normal terse follow-up, where raw_question carries
        the new signal) - but for a pending-clarification reply,
        raw_question IS just the disambiguating fragment ("Genel Cerrahi'yi
        kastettim", no metric wording at all) while ContextResolver had
        already replayed turn 2's FULL original question into
        `state.question`. Planning from the fragment built a near-empty
        plan that then silently inherited turn 1's UNRELATED metric
        (unique_doctor_count) via merge_query_plans, since session memory
        still held turn 1 as the last successfully-persisted plan.

This test exercises RetrieveContextNode directly with a hand-built
AgentState mirroring exactly that turn-3 shape (no LLM/DB needed).
"""

import pytest

from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.state import AgentState
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.planning.models import QueryPlan
from app.services.answerability import AnswerabilityInput

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


class _PromptService:
    context = DatabaseContext(tables=[], views=[VIEW])

    async def retrieve_schema_context(self, question):
        return self.context


@pytest.mark.asyncio
async def test_pending_clarification_reply_plans_from_replayed_question_not_reply_fragment():
    retained = QueryPlan(
        question="Kaç tane farklı doktor 2025'te randevu almış",
        analysis_type="distinct_count",
        metrics=["unique_doctor_count"],
        dimensions=[],
    )
    state = AgentState(
        question="Cerrahi bölümünde 2025'te kaç randevu var",
        raw_question="Genel Cerrahi'yi kastettim",
        retained_query_plan=retained,
        context_follow_up_detected=True,
        forced_filter_override={"department": ["Genel Cerrahi"]},
        answerability_input=AnswerabilityInput(
            raw_question="Genel Cerrahi'yi kastettim",
            resolved_question="Cerrahi bölümünde 2025'te kaç randevu var",
            pending_clarification=True,
        ),
    )

    result = await RetrieveContextNode(_PromptService()).execute(state)

    assert result.query_plan is not None
    assert result.query_plan.metrics == ["appointment_count"]
    assert result.query_plan.metrics != retained.metrics


@pytest.mark.asyncio
async def test_normal_follow_up_still_plans_from_raw_question():
    """Regression guard: a genuine terse follow-up (not a clarification
    reply) must still plan from raw_question, unchanged - only the pending-
    clarification case switches to the replayed full question."""
    retained = QueryPlan(
        question="Doktorlara göre ortalama randevu süresini göster",
        analysis_type="duration_analysis",
        metrics=["appointment_duration_average"],
        dimensions=["GenelRandevuKaynakAdi"],
    )
    state = AgentState(
        question="En yüksek 10 doktoru göster",
        raw_question="En yüksek 10 doktoru göster",
        retained_query_plan=retained,
        context_follow_up_detected=True,
    )

    result = await RetrieveContextNode(_PromptService()).execute(state)

    assert result.query_plan is not None
    assert result.query_plan.metrics == ["appointment_duration_average"]
    assert result.query_plan.limit == 10
