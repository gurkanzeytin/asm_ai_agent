"""Live second-turn regression for structured conversational filters."""

from datetime import UTC, datetime

import pytest

from app.agent.nodes.execute_sql import ExecuteSQLNode
from app.agent.nodes.generate_sql import GenerateSQLNode
from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.nodes.validate_sql import ValidateSQLNode
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.context import ContextManager
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.llm.schemas import LLMResponse
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan, ResolvedFilterPlan
from app.services.deterministic_sql_builder import DeterministicSQL, DeterministicSQLBuilder
from app.services.reporting_service import ReportingService
from app.services.sql_service import SQLService
from app.sql_validator.validator import SQLValidator


class _Parser:
    def parse_sql(self, content: str) -> str:
        return content


class _UnusedProvider:
    calls = 0

    async def generate(self, *args, **kwargs):
        self.calls += 1
        return LLMResponse(content="SELECT 1", model="unused", latency_ms=0)

    def get_metadata(self):
        return {"provider": "test"}


class _PromptService:
    context = DatabaseContext(
        tables=[], views=[ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])]
    )

    async def retrieve_schema_context(self, question):
        return self.context


class _WorkflowService:
    def __init__(self) -> None:
        self.provider = _UnusedProvider()
        self.sql_service = SQLService(self.provider, _Parser(), SQLValidator())
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
        return QueryResult(
            columns=["DoktorId", "appointment_count"],
            rows=[{"DoktorId": 42, "appointment_count": 3}],
            row_count=1,
            execution_time_ms=1,
            success=True,
            executed_at=datetime.now(UTC),
            database_provider="mssql",
        )


class _ExistingPipelineGraph:
    """Runs the existing analytical nodes used by the compiled graph."""

    def __init__(self, workflow_service: _WorkflowService) -> None:
        self.retrieve = RetrieveContextNode(_PromptService())
        self.resolve_filters = ResolveFilterValuesNode()
        self.generate = GenerateSQLNode(workflow_service)
        self.validate = ValidateSQLNode()
        self.execute = ExecuteSQLNode(workflow_service)
        self.states = []

    async def ainvoke(self, state):
        state = await self.retrieve.execute(state)
        state = await self.resolve_filters.execute(state)
        self.states.append(state)
        state = await self.generate.execute(state)
        state = await self.validate.execute(state)
        state = await self.execute.execute(state)
        result = dict(state)
        result.update(
            generated_report=GeneratedReport(
                title="Test", markdown="# Test", provider="test", model="test", latency_ms=0
            ),
            outcome=AgentOutcome.EXECUTE_SQL.value,
        )
        return result


@pytest.mark.asyncio
async def test_same_session_second_turn_executes_retained_plan_with_status_filter():
    session_id = "same-live-session"
    workflow_service = _WorkflowService()
    graph = _ExistingPipelineGraph(workflow_service)
    service = ReportingService(
        graph, ContextManager(store=SessionStore())
    )

    first = await service.run_workflow(
        "2026 Ocak ayında doktorların randevu sayılarını ver.",
        session_id=session_id,
    )
    second = await service.run_workflow(
        "Sadece gerçekleşenleri göster.",
        session_id=session_id,
    )

    first_plan = graph.states[0].query_plan
    second_plan = graph.states[1].query_plan
    assert first_plan is not None and second_plan is not None
    assert first_plan.date_filters[0].start_date == "2026-01-01"
    assert first_plan.date_filters[0].end_date == "2026-01-31"  # effective < 2026-02-01
    assert first_plan.dimensions == ["DoktorId"]
    assert first_plan.metrics == ["appointment_count"]
    assert (first_plan.ranking, first_plan.order) == ("DESC", "DESC")
    assert first_plan.extra_filters == []

    assert second_plan.date_filters == first_plan.date_filters
    assert second_plan.dimensions == first_plan.dimensions
    assert second_plan.metrics == first_plan.metrics
    assert (second_plan.ranking, second_plan.order) == ("DESC", "DESC")
    assert second_plan.extra_filters == ["RandevuDurumu = 'Gerçekleşti'"]

    assert first.outcome == AgentOutcome.EXECUTE_SQL.value
    assert second.outcome == AgentOutcome.EXECUTE_SQL.value
    assert "GROUP BY DoktorId" in first.generated_sql
    assert "ORDER BY appointment_count DESC" in first.generated_sql
    assert "RandevuDurumu" not in first.generated_sql
    assert "BaslangicTarihi >= '2026-01-01'" in second.generated_sql
    assert "DATEADD(day, 1, '2026-01-31')" in second.generated_sql
    assert "GROUP BY DoktorId" in second.generated_sql
    assert "ORDER BY appointment_count DESC" in second.generated_sql
    assert "RandevuDurumu = N'Gerçekleşti'" in second.generated_sql
    assert workflow_service.executed_sql[-1] == second.generated_sql
    assert workflow_service.provider.calls == 0

    compliance = PlanComplianceValidator().check(second.generated_sql, second_plan)
    assert compliance.compliant, compliance.missing


def _grounded(field_name: str, value: str) -> ResolvedFilterPlan:
    return ResolvedFilterPlan(
        field=field_name,
        values=[value],
        grounded=True,
        confidence=1,
        match_type="exact",
    )


@pytest.mark.parametrize(
    ("plan", "predicate"),
    [
        (
            QueryPlan(
                question="q", resolved_filters={"gender": _grounded("gender", "K")}
            ),
            "CinsiyetId = N'K'",
        ),
        (
            QueryPlan(
                question="q",
                resolved_filters={"nationality": _grounded("nationality", "Türkiye")},
            ),
            "Uyruk = N'Türkiye'",
        ),
        (
            QueryPlan(question="q", extra_filters=["RandevuDurumu = 'Gerçekleşti'"]),
            "RandevuDurumu = N'Gerçekleşti'",
        ),
        (
            QueryPlan(question="q", branch_filters=["TEST ASM Gebze"]),
            "SubeAdi = N'TEST ASM Gebze'",
        ),
    ],
)
def test_planned_filter_is_rendered_and_compliant(plan: QueryPlan, predicate: str):
    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    assert predicate in built.sql
    compliance = PlanComplianceValidator().check(built.sql, plan)
    assert compliance.compliant, compliance.missing


def test_duplicate_filter_sources_render_once():
    branch = _grounded("branch", "TEST ASM Gebze")
    plan = QueryPlan(
        question="q",
        branch_filters=["TEST ASM Gebze"],
        resolved_filters={"branch": branch},
    )
    built = DeterministicSQLBuilder().build(plan)
    assert isinstance(built, DeterministicSQL)
    assert built.sql.count("SubeAdi = N'TEST ASM Gebze'") == 1


def test_compliance_rejects_missing_planned_status_filter():
    plan = QueryPlan(question="q", extra_filters=["RandevuDurumu = 'Gerçekleşti'"])
    sql = "SELECT COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu;"
    result = PlanComplianceValidator().check(sql, plan)
    assert not result.compliant
    assert "planned filter RandevuDurumu" in " ".join(result.missing)
