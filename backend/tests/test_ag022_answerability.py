"""AG-022 — Answerability, schema guidance & graceful fallback regression tests.

Covers: answerability guard verdicts, out-of-scope routing and guidance,
rewrite-and-retry loop on retryable database errors, empty-result guidance,
safe-error fallback synthesis, and controlled outcome tagging. Deterministic —
no LLM, no real database.
"""

from datetime import datetime

import pytest

from app.agent.graph import route_after_execution, route_by_intent
from app.agent.nodes.execute_sql import ExecuteSQLNode, _retryable_error
from app.agent.nodes.generate_out_of_scope import GenerateOutOfScopeNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.generated_sql import GeneratedSQL
from app.application_models.intent import IntentResult, IntentType
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.reporting.report_classifier import ReportType
from app.reporting.template_renderer import TemplateReportRenderer
from app.services.answerability import AnswerabilityGuard
from app.services.reporting_service import ReportingService


def make_query_result(rows: list[dict], columns: list[str]) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )


def make_generated_sql(sql: str = "SELECT 1;") -> GeneratedSQL:
    return GeneratedSQL(sql=sql, provider="test", model="test", latency_ms=0.0)


def intent(value: IntentType, confidence: float = 0.95) -> IntentResult:
    return IntentResult(
        intent=value, confidence=confidence, reason="test", matched_keywords=[], metadata={}
    )


# ─────────────────────────────────────────────
# Answerability guard
# ─────────────────────────────────────────────

class TestAnswerabilityGuard:
    def setup_method(self) -> None:
        self.guard = AnswerabilityGuard()

    @pytest.mark.parametrize(
        "question",
        [
            "Kardiyoloji doktorlarını göster",
            "Bugün kaç randevu oluşturuldu?",
            "En yoğun bölüm hangisi?",
            "Son 6 ayın randevularını analiz et",
            "Hastaları listele",
            "Psikiyatri",
        ],
    )
    def test_domain_questions_are_answerable(self, question):
        assert self.guard.assess(question).answerable

    @pytest.mark.parametrize(
        "question",
        [
            "Bugün hava nasıl olacak?",
            "Bitcoin fiyatı ne kadar?",
            "Bana bir şiir yazar mısın?",
            "asdf qwerty lorem ipsum",
        ],
    )
    def test_non_domain_questions_are_not_answerable(self, question):
        assert not self.guard.assess(question).answerable

    def test_guard_fails_open_on_internal_error(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(self.guard._query_analyzer, "analyze", boom)
        result = self.guard.assess("herhangi bir soru")
        assert result.answerable
        assert result.reason == "guard_error_failed_open"


# ─────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────

class TestRouting:
    def test_unanswerable_database_query_routes_out_of_scope(self):
        state = AgentState(
            question="Bitcoin fiyatı?",
            intent=intent(IntentType.DATABASE_QUERY),
            answerable=False,
        )
        assert route_by_intent(state) == "out_of_scope"

    def test_answerable_database_query_routes_normally(self):
        state = AgentState(
            question="Bugün kaç randevu var?",
            intent=intent(IntentType.DATABASE_QUERY),
            answerable=True,
        )
        assert route_by_intent(state) == "database_query"

    def test_guard_verdict_missing_fails_open(self):
        state = AgentState(
            question="Bugün kaç randevu var?",
            intent=intent(IntentType.DATABASE_QUERY),
        )
        assert route_by_intent(state) == "database_query"

    def test_ambiguity_takes_precedence_over_out_of_scope(self):
        from app.application_models.query_analysis import AmbiguityResult

        state = AgentState(
            question="en iyi doktor kim",
            intent=intent(IntentType.DATABASE_QUERY),
            answerable=False,
            ambiguity=AmbiguityResult(matched_phrase="en iyi", question="?", options=[]),
        )
        assert route_by_intent(state) == "unknown"

    def test_retry_route_taken_once(self):
        state = AgentState(
            question="q", last_execution_error="Invalid column name 'x'", sql_retry_count=1
        )
        assert route_after_execution(state) == "retry"

    def test_no_retry_when_errors_present(self):
        state = AgentState(
            question="q",
            last_execution_error="Invalid column name 'x'",
            sql_retry_count=1,
            errors=["ExecuteSQLNode failed: Invalid column name 'x'"],
        )
        assert route_after_execution(state) == "continue"

    def test_clean_execution_continues(self):
        assert route_after_execution(AgentState(question="q")) == "continue"


# ─────────────────────────────────────────────
# Out-of-scope node
# ─────────────────────────────────────────────

class TestOutOfScopeNode:
    @pytest.mark.asyncio
    async def test_returns_schema_guidance_report(self):
        node = GenerateOutOfScopeNode()
        state = await node.execute(AgentState(question="Bitcoin fiyatı?"))
        assert state.outcome == AgentOutcome.OUT_OF_SCOPE.value
        assert state.generated_report is not None
        assert "Randevular" in state.generated_report.markdown
        assert "Örnek sorular" in state.generated_report.markdown
        assert not state.errors


# ─────────────────────────────────────────────
# Rewrite-and-retry
# ─────────────────────────────────────────────

class FakeWorkflowService:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    async def execute_query(self, sql: str) -> QueryResult:
        self.calls += 1
        if self.error:
            raise self.error
        return make_query_result([{"n": 1}], ["n"])


class TestExecuteRetry:
    def test_retryable_error_classifier(self):
        assert _retryable_error("Invalid column name 'doktor_adi'")
        assert _retryable_error("Incorrect syntax near 'SELECT'")
        assert not _retryable_error("Login failed for user 'svc'")
        assert not _retryable_error("timeout")

    @pytest.mark.asyncio
    async def test_first_retryable_failure_schedules_retry(self):
        node = ExecuteSQLNode(FakeWorkflowService(RuntimeError("Invalid column name 'x'")))
        state = AgentState(question="q", generated_sql=make_generated_sql())
        result = await node.execute(state)
        assert result.sql_retry_count == 1
        assert result.last_execution_error is not None
        assert not result.errors  # retry loop stays open

    @pytest.mark.asyncio
    async def test_second_failure_records_error(self):
        node = ExecuteSQLNode(FakeWorkflowService(RuntimeError("Invalid column name 'x'")))
        state = AgentState(
            question="q", generated_sql=make_generated_sql(), sql_retry_count=1
        )
        result = await node.execute(state)
        assert result.errors

    @pytest.mark.asyncio
    async def test_non_retryable_failure_records_error_immediately(self):
        node = ExecuteSQLNode(FakeWorkflowService(RuntimeError("Login failed for user 'svc'")))
        state = AgentState(question="q", generated_sql=make_generated_sql())
        result = await node.execute(state)
        assert result.errors
        assert result.sql_retry_count == 0

    @pytest.mark.asyncio
    async def test_success_after_retry_resolves_rewrite_and_retry(self):
        node = ExecuteSQLNode(FakeWorkflowService())
        state = AgentState(
            question="q", generated_sql=make_generated_sql(), sql_retry_count=1
        )
        result = await node.execute(state)
        assert result.outcome == AgentOutcome.REWRITE_AND_RETRY.value
        assert result.last_execution_error is None
        assert result.query_result is not None


# ─────────────────────────────────────────────
# Empty result guidance
# ─────────────────────────────────────────────

class TestNoResultGuidance:
    def test_empty_template_contains_actionable_guidance(self):
        renderer = TemplateReportRenderer()
        result = renderer.render(
            ReportType.EMPTY, make_query_result([], ["ad_soyad"])
        )
        assert result is not None
        assert "Deneyebilecekleriniz" in result.markdown
        assert "Tarih aralığını genişletin" in result.markdown


# ─────────────────────────────────────────────
# Safe error fallback
# ─────────────────────────────────────────────

class FakeGraph:
    """Agent graph stub returning a pre-built final state dict."""

    def __init__(self, final_state: dict):
        self.final_state = final_state

    async def ainvoke(self, initial_state):
        return self.final_state


class TestSafeErrorFallback:
    @pytest.mark.asyncio
    async def test_no_report_synthesizes_safe_error(self):
        graph = FakeGraph({"errors": ["GenerateSQLNode failed: LLM timeout"]})
        service = ReportingService(agent_graph=graph)
        result = await service.run_workflow("Bugün kaç randevu var?", session_id=None)

        assert result.outcome == AgentOutcome.SAFE_ERROR.value
        assert result.generated_report is not None
        assert "Yanıt Oluşturulamadı" in result.generated_report.markdown
        # never leak technical details to the user
        assert "timeout" not in result.generated_report.markdown.lower()
        assert result.errors  # diagnostics preserved for observability

    @pytest.mark.asyncio
    async def test_existing_report_is_untouched(self):
        report = GeneratedReport(
            title="T", markdown="# T", provider="static", model="m", latency_ms=0.0
        )
        graph = FakeGraph(
            {"generated_report": report, "outcome": AgentOutcome.EXECUTE_SQL.value}
        )
        service = ReportingService(agent_graph=graph)
        result = await service.run_workflow("Bugün kaç randevu var?", session_id=None)
        assert result.outcome == AgentOutcome.EXECUTE_SQL.value
        assert result.generated_report is report


# ─────────────────────────────────────────────
# Outcome tagging in existing nodes
# ─────────────────────────────────────────────

class TestOutcomeTagging:
    @pytest.mark.asyncio
    async def test_clarification_node_tags_outcome(self):
        from app.agent.nodes.generate_clarification import GenerateClarificationNode

        state = await GenerateClarificationNode().execute(AgentState(question="?"))
        assert state.outcome == AgentOutcome.ASK_CLARIFICATION.value

    @pytest.mark.asyncio
    async def test_help_node_tags_outcome(self):
        from app.agent.nodes.generate_help import GenerateHelpNode

        class FakeHelp:
            def get_help_markdown(self) -> str:
                return "# Help"

        state = await GenerateHelpNode(FakeHelp()).execute(AgentState(question="yardım"))
        assert state.outcome == AgentOutcome.RETURN_HELP.value
