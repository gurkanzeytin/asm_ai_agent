from datetime import date

import pytest

from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.application_models.query_analysis import AmbiguityResult
from app.context import ContextManager
from app.context.models import ConversationContext, PendingClarification
from app.context.resolver import ContextResolver
from app.context.session_store import SessionStore
from app.database_intelligence.models import ViewMetadata
from app.planning.planner import QueryPlanner
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.services.query_analyzer import QueryAnalyzer
from app.services.reporting_service import ReportingService


class _FakeGraph:
    def __init__(self, state: dict):
        self.state = state

    async def ainvoke(self, _initial_state):
        return self.state


def _report() -> GeneratedReport:
    return GeneratedReport(
        title="Netleştirme Gerekli",
        markdown="Bir dönem seçin.",
        provider="static",
        model="test",
        latency_ms=0.0,
    )


@pytest.mark.parametrize(
    "question",
    [
        "daha once gelenlerden bu yil da gelen kac kisi var",
        "gecmiste gelen kisilerden bu yil yeniden gelen kac kisi var",
        "onceden gelmis hastalardan bu sene tekrar gelenlerin sayisi",
    ],
)
def test_unbounded_history_overlap_requests_a_targeted_period_clarification(question):
    ambiguity = QueryAnalyzer(today=date(2026, 8, 2)).detect_ambiguity(question)

    assert ambiguity is not None
    assert ambiguity.matched_phrase == "history_period"
    assert "hangi dönemi" in ambiguity.question
    assert "Bir önceki takvim yılı" in ambiguity.options


def test_unrelated_previous_wording_is_not_blocked():
    ambiguity = QueryAnalyzer(today=date(2026, 8, 2)).detect_ambiguity(
        "randevular ortalama ne kadar once aliniyor"
    )

    assert ambiguity is None


def test_current_year_lead_time_question_is_not_mistaken_for_history_overlap():
    ambiguity = QueryAnalyzer(today=date(2026, 8, 2)).detect_ambiguity(
        "bu yil hastalar randevuyu onceden ortalama kac gun once almis"
    )

    assert ambiguity is None


def test_unspecified_duration_basis_requests_a_targeted_clarification():
    ambiguity = QueryAnalyzer(today=date(2026, 8, 2)).detect_ambiguity(
        "randevular ortalama ne kadar surmus"
    )

    assert ambiguity is not None
    assert ambiguity.matched_phrase == "duration_basis"
    assert ambiguity.options == [
        "Planlanan randevu süresi",
        "Fiili süre (başlangıç-bitiş farkı)",
    ]


@pytest.mark.parametrize(
    "question",
    [
        "2025 ortalama randevu suresi",
        "randevularin fiili suresi ortalama ne kadar",
    ],
)
def test_explicit_duration_basis_is_not_blocked(question):
    assert QueryAnalyzer(today=date(2026, 8, 2)).detect_ambiguity(question) is None


@pytest.mark.asyncio
async def test_history_clarification_is_persisted_without_overwriting_context():
    ambiguity = AmbiguityResult(
        matched_phrase="history_period",
        question="Hangi önceki dönem?",
        options=["Bir önceki takvim yılı"],
    )
    manager = ContextManager(store=SessionStore())
    service = ReportingService(
        agent_graph=_FakeGraph(
            {
                "ambiguity": ambiguity,
                "generated_report": _report(),
                "outcome": AgentOutcome.ASK_CLARIFICATION.value,
            }
        ),
        context_manager=manager,
    )

    result = await service.run_workflow(
        "daha once gelenlerden bu yil da gelen kac kisi var",
        session_id="clarification-session",
    )

    pending = manager.get_pending_clarification("clarification-session")
    assert result.outcome == AgentOutcome.ASK_CLARIFICATION.value
    assert pending is not None
    assert pending.field == "history_period"
    assert pending.original_question == result.question
    assert manager.turn_count("clarification-session") == 0


@pytest.mark.parametrize(
    ("original", "reply"),
    [
        ("daha once gelenlerden bu yil da gelen kac kisi var", "Bir önceki takvim yılı"),
        ("gecmiste gelen kisilerden bu yil yeniden gelen kac kisi var", "2024"),
    ],
)
def test_history_period_reply_resumes_the_original_question(original, reply):
    context = ConversationContext(
        session_id="s1",
        pending_clarification=PendingClarification(
            field="history_period",
            reason="Hangi önceki dönem?",
            choices=["Bir önceki takvim yılı"],
            original_question=original,
        ),
    )

    resolution = ContextResolver().resolve(reply, context)

    assert resolution.pending_clarification_resolved is True
    assert all(
        marker not in resolution.resolved_question.casefold()
        for marker in ("daha once", "gecmiste")
    )
    assert "bu yil" in resolution.resolved_question


@pytest.mark.parametrize(
    ("reply", "expected_metric"),
    [
        ("Planlanan randevu süresi", "appointment_duration_average"),
        ("Fiili süre başlangıç bitiş farkı", "actual_duration_from_dates"),
    ],
)
def test_duration_basis_reply_resumes_with_the_selected_metric(reply, expected_metric):
    original = "randevular ortalama ne kadar surmus"
    context = ConversationContext(
        session_id="s2",
        pending_clarification=PendingClarification(
            field="duration_basis",
            reason="Hangi süre?",
            choices=["Planlanan randevu süresi", "Fiili süre"],
            original_question=original,
        ),
    )
    resolution = ContextResolver().resolve(reply, context)
    analyzer = QueryAnalyzer(today=date(2026, 8, 2))
    plan = QueryPlanner().build_plan(
        resolution.resolved_question,
        analyzer.analyze(resolution.resolved_question),
        tables=[],
        views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])],
    )

    assert resolution.pending_clarification_resolved is True
    assert plan.metrics == [expected_metric]


def test_resumed_previous_year_question_builds_period_overlap_sql():
    question = "gecen yil gelenlerden bu yil da gelen kac kisi var"
    analyzer = QueryAnalyzer(today=date(2026, 8, 2))
    analysis = analyzer.analyze(question)
    plan = QueryPlanner().build_plan(
        question,
        analysis,
        tables=[],
        views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])],
    )
    built = DeterministicSQLBuilder().build(plan)

    assert plan.analysis_type == "repeat_behavior"
    assert plan.metrics == ["multi_period_patient_overlap_count"]
    assert len(plan.periods) == 2
    assert isinstance(built, DeterministicSQL)
    assert "SELECT HastaId" in built.sql
    assert "in_baseline_period = 1 AND in_current_period = 1" in built.sql
