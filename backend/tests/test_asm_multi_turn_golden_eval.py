import json
import re
from datetime import date, datetime, timedelta
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


def _month_bounds(anchor: date) -> tuple[date, date]:
    """First and last day of the month `anchor` falls in."""
    first = anchor.replace(day=1)
    last = date(
        first.year + (first.month == 12),
        first.month % 12 + 1,
        1,
    ) - timedelta(days=1)
    return first, last


def _relative_date_placeholders(today: date) -> dict[str, str]:
    """Placeholder -> ISO date, resolved against the run date.

    Relative wording ("bugün", "bu ay", "geçen ay") resolves against the real
    system clock inside the planner, so the golden dataset must not freeze the
    answer: MT-003 hard-coded July 2026 for "Bu ay" and failed in every other
    month. Absolute wording in the dataset ("Ocak 2026", "2025 Mayıs") stays a
    literal — it is not relative and must not drift.
    """
    current_start, current_end = _month_bounds(today)
    previous_start, previous_end = _month_bounds(current_start - timedelta(days=1))
    return {
        "{today}": today.isoformat(),
        "{current_month_start}": current_start.isoformat(),
        "{current_month_end}": current_end.isoformat(),
        "{previous_month_start}": previous_start.isoformat(),
        "{previous_month_end}": previous_end.isoformat(),
    }


def _load_scenarios() -> list[dict]:
    text = DATASET_PATH.read_text(encoding="utf-8")
    for placeholder, value in _relative_date_placeholders(date.today()).items():
        text = text.replace(placeholder, value)
    # A typo'd placeholder would otherwise reach the assertions as a literal
    # string and fail with a confusing date mismatch instead of naming itself.
    unresolved = sorted(set(re.findall(r'"(\{[a-z_]+\})"', text)))
    assert not unresolved, f"çözülmemiş yer tutucu: {unresolved}"

    raw = json.loads(text)
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


@pytest.mark.parametrize(
    "today,expected",
    [
        # Yıl sınırı: ocakta "geçen ay" bir önceki yılın aralığıdır.
        (
            date(2026, 1, 15),
            ("2026-01-01", "2026-01-31", "2025-12-01", "2025-12-31"),
        ),
        # Artık yıl: şubat 29 çeker.
        (
            date(2028, 3, 10),
            ("2028-03-01", "2028-03-31", "2028-02-01", "2028-02-29"),
        ),
        # Artık olmayan yıl.
        (
            date(2026, 3, 10),
            ("2026-03-01", "2026-03-31", "2026-02-01", "2026-02-28"),
        ),
        # Ayın ilk günü: "bu ay" yine o ayın tamamıdır.
        (
            date(2026, 8, 1),
            ("2026-08-01", "2026-08-31", "2026-07-01", "2026-07-31"),
        ),
        # 31 günlük aydan 30 günlük aya.
        (
            date(2026, 7, 31),
            ("2026-07-01", "2026-07-31", "2026-06-01", "2026-06-30"),
        ),
        # Aralık: "bu ay" yıl sonuna dayanır.
        (
            date(2026, 12, 5),
            ("2026-12-01", "2026-12-31", "2026-11-01", "2026-11-30"),
        ),
    ],
)
def test_relative_date_placeholders_resolve_against_the_run_date(today, expected):
    resolved = _relative_date_placeholders(today)

    assert resolved["{today}"] == today.isoformat()
    assert (
        resolved["{current_month_start}"],
        resolved["{current_month_end}"],
        resolved["{previous_month_start}"],
        resolved["{previous_month_end}"],
    ) == expected


def test_golden_dataset_has_no_frozen_relative_dates():
    """Relative wording must carry a placeholder, never a literal date — the
    MT-003 failure mode. Absolute wording ("Ocak 2026") is exempt: it names its
    own month and is supposed to stay frozen.
    """
    # Yer tutucuyu, JSON'ın kendi süslü parantezlerine dokunmadan işaretle.
    marked = re.sub(r'"\{[a-z_]+\}"', '"__PLACEHOLDER__"', DATASET_PATH.read_text(encoding="utf-8"))
    relative_markers = ("bu ay", "gecen ay", "bu yil", "gecen yil", "bugun", "son 30 gun")

    offenders = []
    for scenario in json.loads(marked)["scenarios"]:
        # Göreli bir kapsam bir kez kurulunca sonraki takip turlarında da taşınır
        # ("Bu ay ...", sonra "Bunu grafik ciz") — o turlar da donmuş olamaz.
        relative_scope = False
        for turn in scenario["turns"]:
            if any(marker in turn["question"].lower() for marker in relative_markers):
                relative_scope = True
            if not relative_scope:
                continue
            expected = turn["expected"]
            for key in ("date_start", "date_end"):
                value = expected.get(key)
                if value and value != "__PLACEHOLDER__":
                    offenders.append(f"{scenario['id']} {key}={value} ({turn['question']})")

    assert not offenders, "göreli soruda donmuş tarih: " + "; ".join(offenders)
