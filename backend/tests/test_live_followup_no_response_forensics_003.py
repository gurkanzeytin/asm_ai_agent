"""LIVE-FOLLOWUP-NO-RESPONSE-FORENSICS-003 regression.

Reproduces the exact two literal live turns through the REAL compiled agent
graph (AgentGraphBuilder) — not the abbreviated node subset used by
test_conversational_filter_sql_live_fix.py, which skips analyze_intent,
analyze_results, generate_insights, generate_observations, and generate_report
entirely. Only the two true I/O boundaries (LLM provider, SQL execution) are
faked; every planning/merge/analytics/reporting stage the live app actually
runs is exercised for real, including a genuine zero-row second turn.
"""

from datetime import UTC, datetime

import pytest

from app.agent.graph import AgentGraphBuilder
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.context import ContextManager
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.llm.schemas import LLMResponse
from app.services.reporting_service import ReportingService
from app.services.workflow_streaming import stream_workflow


class _NeverCalledProvider:
    """Fails the test loudly if any stage falls back to an LLM call — the
    deterministic plan for both turns must never need one."""

    async def generate(self, *args, **kwargs):
        raise AssertionError("LLM provider must not be called for this deterministic scenario")

    def get_metadata(self):
        return {"provider": "unused"}


class _PromptService:
    context = DatabaseContext(
        tables=[], views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])]
    )

    async def retrieve_schema_context(self, question):
        return self.context

    async def render_sql_prompt(self, question, database_context=None):
        return "unused prompt"

    async def render_report_prompt(self, question, sql, query_result):
        return "unused prompt"


class _ScriptedExecutionWorkflowService:
    """Real SQLService/ReportService wiring; only SQL execution is scripted
    per-call so turn 1 returns doctor-grouped rows and turn 2 returns zero
    rows for the SAME (status-filtered) deterministic SQL."""

    def __init__(self, sql_service, report_service, row_counts_by_call: list[int]):
        self.sql_service = sql_service
        self.report_service = report_service
        self._row_counts = list(row_counts_by_call)
        self.executed_sql: list[str] = []

    async def execute_sql_generation(
        self, question, database_context=None, error_feedback=None, query_plan=None
    ):
        generated = await self.sql_service.generate_sql(
            "test prompt",
            question=question,
            database_context=database_context,
            query_plan=query_plan,
        )
        return generated.model_copy(update={"rendered_prompt": "test prompt"})

    async def execute_query(self, sql: str) -> QueryResult:
        self.executed_sql.append(sql)
        row_count = self._row_counts.pop(0) if self._row_counts else 0
        rows = (
            [{"DoktorId": 42, "appointment_count": 3}] if row_count else []
        )
        return QueryResult(
            columns=["DoktorId", "appointment_count"],
            rows=rows,
            row_count=row_count,
            execution_time_ms=1,
            success=True,
            executed_at=datetime.now(UTC),
            database_provider="mssql",
        )

    async def execute_report_generation(self, question, sql, query_result, execution_id=None, insights=None):
        return await self.report_service.generate_report(
            question, sql, query_result, execution_id, insights=insights
        )


def _build_service(row_counts_by_call: list[int]) -> tuple[ReportingService, _ScriptedExecutionWorkflowService]:
    from app.parsers.output_parser import OutputParser
    from app.services.report_service import ReportService
    from app.services.sql_service import SQLService
    from app.sql_validator.validator import SQLValidator

    provider = _NeverCalledProvider()
    sql_service = SQLService(provider, OutputParser(), SQLValidator())
    report_service = ReportService(_PromptService(), provider)
    workflow_service = _ScriptedExecutionWorkflowService(sql_service, report_service, row_counts_by_call)

    agent_graph = AgentGraphBuilder(
        prompt_service=_PromptService(),
        workflow_service=workflow_service,
        llm_provider=provider,
    ).build()

    service = ReportingService(agent_graph, ContextManager(store=SessionStore()))
    return service, workflow_service


@pytest.mark.asyncio
async def test_live_two_turn_flow_zero_row_followup_produces_visible_answer():
    """Turn 1 (doctor-grouped counts) then Turn 2 ('Yalnız gerçekleşenleri
    göster.') resolving to zero rows must still terminate with a non-empty
    Turkish report, NO_RESULT_GUIDANCE (never SAFE_ERROR), and a real terminal
    stream event — exactly the boundary the live app reportedly loses."""
    session_id = "live-forensics-003"
    service, workflow_service = _build_service(row_counts_by_call=[1, 0])

    turn1_events = []
    async for event in stream_workflow(
        service, "Ocak 2026 için doktor bazında randevu sayılarını göster.", session_id
    ):
        turn1_events.append(event)
    turn1_kinds = [event.kind for event in turn1_events]
    assert turn1_kinds[-1] == "complete", turn1_kinds
    turn1 = turn1_events[-1].result
    assert turn1 is not None
    assert turn1.errors == []
    assert turn1.outcome == AgentOutcome.EXECUTE_SQL.value
    assert turn1.session_id == session_id

    turn2_events = []
    async for event in stream_workflow(
        service, "Yalnız gerçekleşenleri göster.", session_id
    ):
        turn2_events.append(event)
    turn2_kinds = [event.kind for event in turn2_events]

    # 1. Exactly one terminal event, and it must be "complete" (never a
    #    silently dropped/errored stream) — the actual live symptom.
    assert turn2_kinds[-1] == "complete", turn2_kinds
    assert turn2_kinds.count("complete") == 1
    assert "error" not in turn2_kinds

    turn2 = turn2_events[-1].result
    assert turn2 is not None

    # 2. Same session both turns.
    assert turn2.session_id == session_id == turn1.session_id

    # 3. Zero rows is not an error.
    assert turn2.errors == []
    assert turn2.outcome != AgentOutcome.SAFE_ERROR.value
    assert turn2.outcome == AgentOutcome.NO_RESULT_GUIDANCE.value

    # 4. A non-empty Turkish terminal report was produced.
    assert turn2.generated_report is not None
    assert turn2.generated_report.markdown.strip() != ""

    # 5. Turn 2's final merged plan is correct and inherited turn 1's context.
    assert turn2.generated_sql is not None
    assert "GROUP BY DoktorId" in turn2.generated_sql
    assert "BaslangicTarihi >= '2026-01-01'" in turn2.generated_sql
    assert "DATEADD(day, 1, '2026-01-31')" in turn2.generated_sql
    assert "RandevuDurumu = N'Gerçekleşti'" in turn2.generated_sql

    # 6. Both turns resolved deterministically (no LLM fallback was needed).
    assert workflow_service.executed_sql[-1] == turn2.generated_sql
