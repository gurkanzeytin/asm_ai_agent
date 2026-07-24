import json
from datetime import date, datetime
from pathlib import Path

import pytest

from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.state import AgentState
from app.application_models.workflow_models import QueryResult
from app.context import ContextManager
from app.context.session_store import SessionStore
from app.database_intelligence.models import DatabaseContext, ViewMetadata
from app.planning.compliance import PlanComplianceValidator
from app.planning.models import QueryPlan
from app.reporting.output_policy import determine_output_policy
from app.services.deterministic_sql_builder import DeterministicSQLBuilder
from app.sql_validator.validator import SQLValidator

VIEW_NAME = "dbo.vw_RandevuRaporu"
VIEW = ViewMetadata(name=VIEW_NAME, columns=[])
DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "resources"
    / "asm_multi_turn_golden_eval.json"
)


class _PromptService:
    context = DatabaseContext(tables=[], views=[VIEW])

    async def retrieve_schema_context(self, question):
        return self.context


def _load_scenarios() -> list[dict]:
    # "bugün" resolves against the real system clock in the planner; the golden
    # dataset carries a {today} placeholder instead of a frozen date.
    text = DATASET_PATH.read_text(encoding="utf-8")
    raw = json.loads(text.replace("{today}", date.today().isoformat()))
    assert raw["view"] == VIEW_NAME
    return raw["scenarios"]


def _dummy_result() -> QueryResult:
    return QueryResult(
        columns=["value"],
        rows=[{"value": 1}],
        row_count=1,
        execution_time_ms=1.0,
        success=True,
        executed_at=datetime.now(),
        database_provider="mssql",
    )


async def _run_turn(
    manager: ContextManager,
    session_id: str,
    question: str,
) -> tuple[QueryPlan, bool]:
    resolution = manager.resolve(question, session_id)
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
    state = await RetrieveContextNode(_PromptService()).execute(state)
    assert state.query_plan is not None, question
    assert not state.errors, state.errors
    updated = manager.update(
        resolution,
        session_id,
        query_plan=state.query_plan,
    )
    assert updated is True, question
    return state.query_plan, resolution.follow_up_detected


def _assert_plan(case_id: str, turn_index: int, plan: QueryPlan, expected: dict) -> None:
    label = f"{case_id} turn {turn_index}"
    assert plan.analysis_type == expected["analysis_type"], label
    assert plan.metrics == expected["metrics"], label
    assert plan.dimensions == expected["dimensions"], label
    if "limit" in expected:
        assert plan.limit == expected["limit"], label
    if "ranking" in expected:
        assert plan.ranking == expected["ranking"], label
    if expected.get("date_column"):
        assert plan.date_filters, label
        date_filter = plan.date_filters[0]
        assert date_filter.column == expected["date_column"], label
        assert date_filter.start_date == expected["date_start"], label
        assert date_filter.end_date == expected["date_end"], label
    for needle in expected["extra_include"]:
        assert any(needle in value for value in plan.extra_filters), label
    for needle in expected["extra_exclude"]:
        assert not any(needle in value for value in plan.extra_filters), label


def _assert_output_policy(question: str, expected: dict, sql: str | None) -> None:
    query_result = (
        _dummy_result()
        if expected["response_mode"] in {"data", "visualization"}
        else None
    )
    policy = determine_output_policy(
        question=question,
        outcome=None,
        generated_sql=sql,
        query_result=query_result,
        analytics=None,
    )
    expected_mode = expected["response_mode"] or "answer"
    assert policy.response_mode == expected_mode, question
    if expected["visible_sections"]:
        assert policy.visible_sections == expected["visible_sections"], question


def test_asm_multi_turn_golden_eval_shape():
    scenarios = _load_scenarios()
    ids = [scenario["id"] for scenario in scenarios]
    turn_count = sum(len(scenario["turns"]) for scenario in scenarios)

    assert len(ids) == len(set(ids))
    assert len(scenarios) >= 10
    assert turn_count >= 30


@pytest.mark.asyncio
async def test_asm_multi_turn_golden_eval_matches_context_planner_sql_and_output():
    builder = DeterministicSQLBuilder()
    validator = SQLValidator()
    compliance = PlanComplianceValidator()

    for scenario in _load_scenarios():
        manager = ContextManager(store=SessionStore())
        session_id = f"golden-{scenario['id']}"
        for index, turn in enumerate(scenario["turns"], start=1):
            expected = turn["expected"]
            plan, follow_up = await _run_turn(manager, session_id, turn["question"])

            assert follow_up is expected["follow_up"], f"{scenario['id']} turn {index}"
            _assert_plan(scenario["id"], index, plan, expected)

            built = builder.build(plan)
            assert hasattr(built, "sql"), f"{scenario['id']} turn {index}"
            validation = validator.validate(built.sql)
            assert validation.valid, f"{scenario['id']} turn {index}"
            sql_compliance = compliance.check(built.sql, plan)
            assert sql_compliance.compliant, sql_compliance.missing
            _assert_output_policy(turn["question"], expected, built.sql)
