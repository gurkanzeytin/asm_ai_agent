"""DOCTOR-DISPLAY-NAME-ENRICHMENT-001 real-pipeline integration tests (L, M).

Runs the actual compiled agent graph (AgentGraphBuilder) end to end — the
same real node set (analyze_intent -> ... -> generate_report) exercised by
LIVE-FOLLOWUP-NO-RESPONSE-FORENSICS-003 — with a real DoctorLabelResolver
wired the same way AgentGraphBuilder.build() wires it in production: off
workflow_service.execution_service.repository. Only the LLM provider and the
raw SQL/doctor-lookup execution are faked.

Proves: a doctor-grouped analytical result becomes user-facing doctor names
in the report/visualization without changing row counts or the QueryPlan's
DoktorId grouping, and that this survives a same-session follow-up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.agent.graph import AgentGraphBuilder
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.context import ContextManager
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.services.doctor_label_resolver import DOKTOR_ADI_COLUMN, DOKTOR_ID_COLUMN
from app.services.reporting_service import ReportingService
from app.services.workflow_streaming import stream_workflow

_DOCTOR_ROWS = [
    {"DoktorId": 7773, "appointment_count": 43232},
    {"DoktorId": 2549, "appointment_count": 120},
]


class _NeverCalledProvider:
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


class _FakeDoctorLookupRepository:
    """Stands in for the read-only analytical repository for the doctor
    lookup queries only (official + non-doctor label set + historical
    fallback) — never used for the main analytical SQL execution."""

    def __init__(self):
        self.official_rows = [
            {"DoktorId": 7773, "DoktorAdi": "ÇAĞATAY ÖKTENLİ"},
            {"DoktorId": 2549, "DoktorAdi": "NAMIK KEMAL AKPINAR"},
        ]

    async def execute_query(self, query: str, params: dict | None = None):
        if "KaynakTipiAdi = N'Doktor'" in query:
            return self.official_rows
        if "KaynakTipiAdi <> N'Doktor'" in query:
            return []
        if "dbo.vw_RandevuRaporu" in query:
            return []
        raise AssertionError(f"unexpected lookup query: {query}")


class _ScriptedExecutionWorkflowService:
    def __init__(self, sql_service, report_service, row_batches: list[list[dict]]):
        self.sql_service = sql_service
        self.report_service = report_service
        self._row_batches = list(row_batches)
        self.executed_sql: list[str] = []
        # Wired exactly like production AppContainer: the doctor label
        # resolver reuses this same repository handle.
        self.execution_service = SimpleNamespace(repository=_FakeDoctorLookupRepository())

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
        rows = self._row_batches.pop(0) if self._row_batches else []
        columns = list(rows[0].keys()) if rows else ["DoktorId", "appointment_count"]
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            execution_time_ms=1,
            success=True,
            executed_at=datetime.now(UTC),
            database_provider="mssql",
        )

    async def execute_report_generation(self, question, sql, query_result, execution_id=None, insights=None):
        return await self.report_service.generate_report(
            question, sql, query_result, execution_id, insights=insights
        )


def _build_service(row_batches: list[list[dict]]):
    from app.services.report_service import ReportService
    from app.services.sql_service import SQLService
    from app.sql_validator.validator import SQLValidator

    provider = _NeverCalledProvider()
    sql_service = SQLService(provider, _Parser(), SQLValidator())
    report_service = ReportService(_PromptService(), provider)
    workflow_service = _ScriptedExecutionWorkflowService(sql_service, report_service, row_batches)

    agent_graph = AgentGraphBuilder(
        prompt_service=_PromptService(),
        workflow_service=workflow_service,
        llm_provider=provider,
    ).build()

    service = ReportingService(agent_graph, ContextManager(store=SessionStore()))
    return service, workflow_service


class _Parser:
    def parse_sql(self, content: str) -> str:
        return content


# L. End-to-end doctor grouping


@pytest.mark.asyncio
async def test_doctor_grouped_result_shows_names_and_preserves_counts():
    service, workflow_service = _build_service(row_batches=[_DOCTOR_ROWS])

    events = []
    async for event in stream_workflow(
        service, "Ocak 2025 için doktor bazında randevu sayılarını göster.", "doctor-e2e"
    ):
        events.append(event)
    assert events[-1].kind == "complete"
    result = events[-1].result
    assert result is not None
    assert result.errors == []
    assert result.outcome == AgentOutcome.EXECUTE_SQL.value

    # SQL still groups by DoktorId — the semantic/planner grouping key is untouched.
    assert result.generated_sql is not None
    assert "GROUP BY DoktorId" in result.generated_sql
    assert "DoktorId" in result.generated_sql

    # Raw result contains DoktorId; enriched display contains DoktorAdi.
    qr = result.query_result
    assert qr is not None
    assert DOKTOR_ID_COLUMN in qr.columns
    assert DOKTOR_ADI_COLUMN in qr.columns
    resolved_names = {row[DOKTOR_ID_COLUMN]: row[DOKTOR_ADI_COLUMN] for row in qr.rows}
    assert resolved_names[7773] == "ÇAĞATAY ÖKTENLİ"
    assert resolved_names[2549] == "NAMIK KEMAL AKPINAR"

    # Counts are unchanged by enrichment.
    counts_by_id = {row[DOKTOR_ID_COLUMN]: row["appointment_count"] for row in qr.rows}
    assert counts_by_id[7773] == 43232
    assert counts_by_id[2549] == 120
    assert qr.row_count == len(_DOCTOR_ROWS)

    # Report/visualization refer to doctor names, not raw ids.
    assert result.generated_report is not None
    report_markdown = result.generated_report.markdown
    assert "ÇAĞATAY ÖKTENLİ" in report_markdown or "NAMIK KEMAL AKPINAR" in report_markdown
    assert "7773" not in report_markdown

    # Visualization/category labels use doctor names, not raw ids.
    assert result.analytics is not None
    assert result.analytics.metrics.get("top_category") == "ÇAĞATAY ÖKTENLİ"
    assert result.analytics.visualization is not None


# M. Follow-up preservation


@pytest.mark.asyncio
async def test_doctor_labels_remain_enriched_across_a_status_followup():
    service, workflow_service = _build_service(
        row_batches=[_DOCTOR_ROWS, _DOCTOR_ROWS]
    )
    session_id = "doctor-followup"

    async for event in stream_workflow(
        service, "Ocak 2025 için doktor bazında randevu sayılarını göster.", session_id
    ):
        pass
    turn1 = event.result
    assert turn1 is not None and turn1.errors == []

    async for event in stream_workflow(service, "Yalnız gerçekleşenleri göster.", session_id):
        pass
    turn2 = event.result
    assert turn2 is not None and turn2.errors == []

    # Doctor labels remain enriched on both turns.
    for result in (turn1, turn2):
        qr = result.query_result
        assert qr is not None
        assert DOKTOR_ADI_COLUMN in qr.columns
        names = {row[DOKTOR_ADI_COLUMN] for row in qr.rows}
        assert "ÇAĞATAY ÖKTENLİ" in names

    # Status follow-up correctness: turn 2 SQL groups by DoktorId and adds
    # the status filter — no display label leaked into the semantic plan.
    assert "GROUP BY DoktorId" in turn2.generated_sql
    assert "RandevuDurumu = N'Gerçekleşti'" in turn2.generated_sql
    assert "ÇAĞATAY" not in turn2.generated_sql
    assert "NAMIK KEMAL" not in turn2.generated_sql
