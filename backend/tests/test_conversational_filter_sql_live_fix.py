"""Live second-turn regression for structured conversational filters."""

from datetime import UTC, datetime

import pytest

from app.agent.nodes.execute_sql import ExecuteSQLNode
from app.agent.nodes.generate_sql import GenerateSQLNode
from app.agent.nodes.resolve_filter_values import ResolveFilterValuesNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.nodes.validate_sql import ValidateSQLNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.application_models.outcome import AgentOutcome
from app.application_models.workflow_models import QueryResult
from app.context import ContextManager
from app.context.analytical_signals import merge_query_plans
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.llm.schemas import LLMResponse
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import DateFilterPlan, QueryPlan, ResolvedFilterPlan
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
        self.final_states = []

    async def ainvoke(self, state):
        state = await self.retrieve.execute(state)
        state = await self.resolve_filters.execute(state)
        self.states.append(state)
        state = await self.generate.execute(state)
        state = await self.validate.execute(state)
        state = await self.execute.execute(state)
        self.final_states.append(state)
        result = dict(state)
        # Mirrors ReportingService's own SAFE_ERROR fallback (generated_report
        # stays None when an upstream node recorded an error) so a regression
        # that makes GenerateSQLNode raise is visible as SAFE_ERROR here too,
        # not masked by an unconditionally-forced EXECUTE_SQL outcome.
        if state.errors:
            result.update(generated_report=None, outcome=AgentOutcome.SAFE_ERROR.value)
        else:
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


@pytest.mark.asyncio
async def test_same_session_third_turn_replaces_status_filter_family():
    """AI-INTELLIGENCE regression: a third-turn status change ('beklemede')
    must replace the second turn's status filter ('gerçekleşti') and must not
    be mistaken for a metric switch merely because the metric catalog's
    'waiting_count' synonym ('beklemede olan') overlaps the filter wording."""
    session_id = "same-live-session-turn3"
    workflow_service = _WorkflowService()
    graph = _ExistingPipelineGraph(workflow_service)
    service = ReportingService(graph, ContextManager(store=SessionStore()))

    first = await service.run_workflow(
        "2026 Ocak ayında doktorların randevu sayılarını ver.",
        session_id=session_id,
    )
    second = await service.run_workflow(
        "Sadece gerçekleşenleri göster.",
        session_id=session_id,
    )
    third = await service.run_workflow(
        "O zaman sadece beklemede olanları göster.",
        session_id=session_id,
    )

    first_plan = graph.states[0].query_plan
    second_plan = graph.states[1].query_plan
    third_plan = graph.states[2].query_plan
    assert first_plan is not None and second_plan is not None and third_plan is not None

    # Retained across all three turns.
    assert third_plan.date_filters == first_plan.date_filters
    assert third_plan.dimensions == ["DoktorId"]
    assert third_plan.metrics == ["appointment_count"]
    assert (third_plan.ranking, third_plan.order) == ("DESC", "DESC")

    # Exactly one status filter, and it replaced (not appended to) Gerçekleşti.
    assert third_plan.extra_filters == ["RandevuDurumu = 'Beklemede'"]
    assert "Gerçekleşti" not in third_plan.extra_filters[0]

    third_final_state = graph.final_states[2]
    assert third_final_state.errors == []
    assert third.outcome != AgentOutcome.SAFE_ERROR.value

    assert third.generated_sql is not None
    assert "N'Beklemede'" in third.generated_sql
    assert "Gerçekleşti" not in third.generated_sql
    assert "GROUP BY DoktorId" in third.generated_sql
    assert "ORDER BY appointment_count DESC" in third.generated_sql
    assert workflow_service.executed_sql[-1] == third.generated_sql

    compliance = PlanComplianceValidator().check(third.generated_sql, third_plan)
    assert compliance.compliant, compliance.missing


async def _plan_after_followup(
    first_question: str, second_question: str
) -> tuple[QueryPlan, QueryPlan]:
    """Runs two turns through the real RetrieveContextNode (real QueryAnalyzer +
    QueryPlanner + merge_query_plans) and returns (first_plan, second_plan).

    Deliberately stops before GenerateSQLNode/compliance/SQL generation: those
    stages are unrelated to conversational-memory merge behavior and this
    helper isolates exactly the planner+merge slice the metric/filter
    ambiguity fix lives in.
    """
    manager = ContextManager(store=SessionStore())
    session_id = "plan-after-followup"
    retrieve = RetrieveContextNode(_PromptService())
    resolve_filters = ResolveFilterValuesNode()

    resolution1 = manager.resolve(first_question, session_id)
    state1 = AgentState(
        question=resolution1.resolved_question,
        raw_question=first_question,
        retained_query_plan=None,
        context_follow_up_detected=resolution1.follow_up_detected,
    )
    state1 = await retrieve.execute(state1)
    state1 = await resolve_filters.execute(state1)
    manager.update(resolution1, session_id, query_plan=state1.query_plan)

    resolution2 = manager.resolve(second_question, session_id)
    state2 = AgentState(
        question=resolution2.resolved_question,
        raw_question=second_question,
        retained_query_plan=(
            QueryPlan.model_validate(resolution2.retained_query_plan_snapshot)
            if resolution2.retained_query_plan_snapshot
            else None
        ),
        context_follow_up_detected=resolution2.follow_up_detected,
    )
    state2 = await retrieve.execute(state2)
    state2 = await resolve_filters.execute(state2)

    return state1.query_plan, state2.query_plan


@pytest.mark.asyncio
async def test_same_session_explicit_measure_request_switches_metric_despite_status_overlap():
    """The mirror-image regression of turn 3 above: when the current turn is
    an unambiguous measure/count request ('... sayısı nedir?') that happens to
    also match a status word ('bekleyen' -> RandevuDurumu='Beklemede'), the
    metric MUST switch — filter-restricting wording is what suppresses a
    metric switch, not mere status-value overlap (see
    app.context.analytical_signals._MEASURE_REQUEST_MARKERS)."""
    first_plan, second_plan = await _plan_after_followup(
        "2026 Ocak ayında doktorların randevu sayılarını ver.",
        "Bekleyen randevu sayısı nedir?",
    )
    assert first_plan is not None and second_plan is not None
    assert first_plan.metrics == ["appointment_count"]

    # Explicit measure request wins: metric actually switches this time.
    assert second_plan.metrics == ["waiting_count"]
    # Compatible retained context (date) survives the metric switch.
    assert second_plan.date_filters == first_plan.date_filters


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "expected_metric"),
    [
        # Filter-shaped: no measure noun -> retained metric must survive.
        ("O zaman sadece beklemede olanları göster.", "appointment_count"),
        ("Beklemede olanları göster.", "appointment_count"),
        ("Yalnız gerçekleşenleri göster.", "appointment_count"),
        # Measure-shaped: explicit count/rate noun -> metric switches.
        ("Bekleyen randevu sayısı nedir?", "waiting_count"),
        ("Bekleme oranı nedir?", "waiting_rate"),
    ],
)
async def test_same_status_wording_resolves_to_filter_or_metric_by_phrasing(
    question, expected_metric
):
    """AI-INTELLIGENCE regression (generalized): the SAME status word
    ('bekleyen'/'beklemede') must resolve to a status filter when the wording
    only restricts rows, and to a genuine metric switch when the wording is an
    explicit measure/count request — verified on the structured QueryPlan
    through the real planner + merge pipeline, never on raw text equality."""
    _, second_plan = await _plan_after_followup(
        "2026 Ocak ayında doktorların randevu sayılarını ver.", question
    )
    assert second_plan is not None
    assert second_plan.metrics == [expected_metric], second_plan.metrics


@pytest.mark.parametrize(
    ("first_question", "first_field", "first_value", "second_question", "second_field", "second_value", "predicate_column"),
    [
        ("Pendik şubesini göster.", "branch", "Pendik", "Şimdi Kartal şubesini göster.", "branch", "Kartal", "SubeAdi"),
        ("Kadın hastaları göster.", "gender", "K", "Erkek hastalarla sınırla.", "gender", "E", "CinsiyetId"),
        (
            "Türk hastaları göster.",
            "nationality",
            "Türkiye",
            "Sadece Alman hastaları göster.",
            "nationality",
            "Almanya",
            "Uyruk",
        ),
    ],
)
def test_generic_filter_family_replacement(
    first_question,
    first_field,
    first_value,
    second_question,
    second_field,
    second_value,
    predicate_column,
):
    """A second explicit value for the SAME filter family (branch/gender/
    nationality) must replace, not accumulate onto, the first — mirroring the
    status-filter override semantics, generically across every grounded
    filter family (AI-INTELLIGENCE-016 resolved_filters)."""
    first_plan_kwargs: dict = {"question": first_question, "resolved_filters": {first_field: _grounded(first_field, first_value)}}
    second_plan_kwargs: dict = {
        "question": second_question,
        "resolved_filters": {second_field: _grounded(second_field, second_value)},
    }
    if first_field == "branch":
        first_plan_kwargs["branch_filters"] = [first_value]
    if second_field == "branch":
        second_plan_kwargs["branch_filters"] = [second_value]

    first_plan = QueryPlan(**first_plan_kwargs)
    second_plan = QueryPlan(**second_plan_kwargs)

    merged = merge_query_plans(
        current=second_plan,
        retained=first_plan,
        raw_question=second_question,
        follow_up_detected=True,
    )

    assert merged.resolved_filters[second_field].values == [second_value]
    if second_field == "branch":
        assert merged.branch_filters == [second_value]

    built = DeterministicSQLBuilder().build(merged)
    assert f"{predicate_column} = N'{second_value}'" in built.sql
    assert f"{predicate_column} = N'{first_value}'" not in built.sql


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


def test_multi_field_explicit_override_replaces_branch_date_and_grouping():
    """A follow-up that explicitly restates branch, date/year, and grouping
    together must replace all three at once — none of the first turn's
    values (branch, dimension) may leak into the merged plan, while the
    untouched metric is retained (AI-INTELLIGENCE regression, item K)."""
    retained = QueryPlan(
        question="2025 yılında Gebze şubesinde doktor bazında randevu sayıları.",
        metrics=["appointment_count"],
        dimensions=["DoktorId"],
        aggregation="COUNT(*)",
        branch_filters=["Gebze"],
        resolved_filters={"branch": _grounded("branch", "Gebze")},
        date_filters=[
            DateFilterPlan(
                column="BaslangicTarihi",
                start_date="2025-01-01",
                end_date="2025-12-31",
                expression="2025 yilinda",
            )
        ],
    )
    current_question = "2024 için Ataşehir şubesinde bölüm bazında göster."
    current = QueryPlan(
        question=current_question,
        dimensions=["GenelRandevuBolumAdi"],
        branch_filters=["Ataşehir"],
        resolved_filters={"branch": _grounded("branch", "Ataşehir")},
        date_filters=[
            DateFilterPlan(
                column="BaslangicTarihi",
                start_date="2024-01-01",
                end_date="2024-12-31",
                expression="2024 icin",
            )
        ],
    )

    merged = merge_query_plans(
        current=current,
        retained=retained,
        raw_question=current_question,
        follow_up_detected=True,
    )

    # Explicitly restated fields replaced, no stale Gebze/doctor leakage.
    assert merged.branch_filters == ["Ataşehir"]
    assert merged.resolved_filters["branch"].values == ["Ataşehir"]
    assert merged.dimensions == ["GenelRandevuBolumAdi"]
    assert [f.start_date for f in merged.date_filters] == ["2024-01-01"]
    assert [f.end_date for f in merged.date_filters] == ["2024-12-31"]

    # Untouched metric retained.
    assert merged.metrics == ["appointment_count"]

    built = DeterministicSQLBuilder().build(merged)
    assert "SubeAdi = N'Ataşehir'" in built.sql
    assert "Gebze" not in built.sql
    assert "2024-01-01" in built.sql
    assert "2025-01-01" not in built.sql
