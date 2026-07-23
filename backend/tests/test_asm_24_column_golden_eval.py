import json
from datetime import datetime
from pathlib import Path

from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import ViewMetadata
from app.planning.planner import QueryPlanner
from app.reporting.output_policy import determine_output_policy
from app.semantics import catalog
from app.services.deterministic_sql_builder import DeterministicSQLBuilder
from app.services.query_analyzer import QueryAnalyzer
from app.sql_validator.validator import SQLValidator

VIEW_NAME = "dbo.vw_RandevuRaporu"
VIEW = ViewMetadata(name=VIEW_NAME, columns=[])
DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "resources"
    / "asm_24_column_golden_eval.json"
)


def _load_cases() -> list[dict]:
    raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert raw["view"] == VIEW_NAME
    return raw["cases"]


def _plan(question: str):
    analysis = QueryAnalyzer().analyze(question)
    return QueryPlanner().build_plan(question, analysis, tables=[], views=[VIEW])


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


def test_asm_24_column_golden_eval_ids_are_unique():
    cases = _load_cases()
    ids = [case["id"] for case in cases]

    assert len(ids) == len(set(ids))
    assert len(cases) >= 28


def test_asm_24_column_golden_eval_covers_every_randevu_raporu_column():
    cases = _load_cases()
    covered = {
        column
        for case in cases
        for column in case.get("covered_columns", [])
    }

    assert covered == catalog.load_column_catalog().column_names()


def test_asm_24_column_golden_eval_matches_planner_sql_and_output_policy():
    builder = DeterministicSQLBuilder()
    validator = SQLValidator()

    for case in _load_cases():
        expected = case["expected"]
        ambiguity = QueryAnalyzer().detect_ambiguity(case["question"])
        assert (ambiguity is not None) is expected["clarification_required"], case["id"]

        if expected["clarification_required"]:
            assert not expected["sql_should_build"], case["id"]
            continue

        plan = _plan(case["question"])
        assert plan.answerable is expected["answerable"], case["id"]
        assert plan.analysis_type == expected["analysis_type"], case["id"]
        assert plan.metrics == expected["metrics"], case["id"]
        assert plan.dimensions == expected["dimensions"], case["id"]

        if expected.get("date_column"):
            assert {date_filter.column for date_filter in plan.date_filters} == {
                expected["date_column"]
            }, case["id"]

        built = builder.build(plan)
        if expected["sql_should_build"]:
            assert hasattr(built, "sql"), case["id"]
            validation = validator.validate(built.sql)
            assert validation.valid, case["id"]
            for needle in case["sql"]["must_include"]:
                assert needle in built.sql, case["id"]
            for needle in case["sql"]["must_not_include"]:
                assert needle not in built.sql, case["id"]
        else:
            assert not hasattr(built, "sql"), case["id"]

        output_policy = determine_output_policy(
            question=case["question"],
            outcome=None,
            generated_sql=getattr(built, "sql", None),
            query_result=_dummy_result() if expected["response_mode"] == "data" else None,
            analytics=None,
        )
        assert output_policy.response_mode == expected["response_mode"] or (
            expected["response_mode"] is None and output_policy.response_mode == "answer"
        ), case["id"]
        if expected["visible_sections"]:
            assert output_policy.visible_sections == expected["visible_sections"], case["id"]
