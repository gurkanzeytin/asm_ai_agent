import json
from pathlib import Path

import pytest
from tools.evaluation.__main__ import main
from tools.evaluation.dataset import (
    load_evaluation_dataset,
    select_cases,
    validate_evaluation_dataset,
)
from tools.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationMode,
    ExpectedEvaluation,
    FailureCode,
)
from tools.evaluation.report import compare_with_previous, write_run_reports
from tools.evaluation.runner import EvaluationRunner
from tools.evaluation.scorers import (
    score_final_answer,
    score_result_contract,
    score_routing,
    score_sql_semantics,
)

from app.analytics.result_contracts import NormalizedResult
from app.semantics import examples
from app.semantics.catalog import CatalogValidationError


def test_evaluation_case_schema_validation():
    dataset = load_evaluation_dataset()
    assert len(dataset.cases) >= 75
    assert {case.id for case in dataset.cases if case.id.startswith("E2E-RW-")} >= {
        "E2E-RW-001",
        "E2E-RW-002",
        "E2E-RW-003",
        "E2E-RW-004",
        "E2E-RW-005",
        "E2E-RW-006",
        "E2E-RW-007",
    }


def test_controlled_limitation_is_not_scored_as_unnecessary_clarification():
    case = EvaluationCase(
        id="CONTROLLED-LIMITATION",
        question="Doktor maaşları nedir?",
        category="unanswerable",
        expected=ExpectedEvaluation(answerable=False),
    )

    scored = score_routing(case, clarification_required=True)

    assert scored.passed
    assert scored.failures == []


def test_unknown_column_rejection():
    raw = load_evaluation_dataset().model_dump()
    raw["cases"][0]["sql_requirements"]["must_use_columns"] = ["ImaginaryColumn"]
    with pytest.raises(CatalogValidationError):
        validate_evaluation_dataset(EvaluationDataset(**raw))


def test_unknown_metric_rejection():
    raw = load_evaluation_dataset().model_dump()
    raw["cases"][0]["expected"]["metrics"] = ["imaginary_metric"]
    with pytest.raises(CatalogValidationError):
        validate_evaluation_dataset(EvaluationDataset(**raw))


def test_blind_cases_excluded_from_retrieval():
    retrieved = examples.retrieve_examples(
        "Bu aralar hangi subede iptaller patlamis?",
        "anomaly_comparison",
        ["cancelled_appointment_rate"],
        ["SubeAdi"],
    )
    assert not any(example.id.startswith("RW-") for example in retrieved)


def test_colloquial_blind_v2_is_separate_curated_evaluation_data():
    dataset = load_evaluation_dataset()
    cases = select_cases(dataset, suite="colloquial_blind_v2")

    assert len(cases) == 35
    expected_ids = {
        "COL-BLIND-009",
        "COL-BLIND-013",
        *(f"COL-BLIND-{index:03d}" for index in range(19, 25)),
        "COL-BLIND-026",
        "COL-BLIND-028",
        "COL-BLIND-032",
        "COL-BLIND-033",
        "COL-BLIND-035",
        "COL-BLIND-041",
        "COL-BLIND-042",
        "COL-BLIND-051",
        *(f"COL-BLIND-{index:03d}" for index in range(52, 59)),
        "COL-BLIND-060",
        "COL-BLIND-063",
        "COL-BLIND-065",
        "COL-BLIND-067",
        "COL-BLIND-069",
        *(f"COL-BLIND-{index:03d}" for index in range(71, 76)),
        "COL-BLIND-077",
        "COL-BLIND-079",
    }
    assert {case.id for case in cases} == expected_ids
    assert all(case.blind and case.suite == "colloquial_blind_v2" for case in cases)
    assert len({case.question.casefold() for case in cases}) == len(cases)
    assert len({case.category for case in cases}) >= 12

    production_questions = {
        example.question.casefold() for example in examples.load_golden_dataset().questions
    }
    assert not production_questions.intersection(case.question.casefold() for case in cases)


def test_mentor_surprise_v1_is_a_separate_manually_authored_holdout():
    dataset = load_evaluation_dataset()
    cases = select_cases(dataset, suite="mentor_surprise_v1")

    assert len(cases) == 15
    assert {case.id for case in cases} == {
        "MENTOR-SURPRISE-001",
        "MENTOR-SURPRISE-002",
        "MENTOR-SURPRISE-004",
        "MENTOR-SURPRISE-006",
        "MENTOR-SURPRISE-008",
        "MENTOR-SURPRISE-009",
        "MENTOR-SURPRISE-015",
        "MENTOR-SURPRISE-018",
        "MENTOR-SURPRISE-019",
        "MENTOR-SURPRISE-021",
        "MENTOR-SURPRISE-023",
        "MENTOR-SURPRISE-025",
        "MENTOR-SURPRISE-027",
        "MENTOR-SURPRISE-028",
        "MENTOR-SURPRISE-029",
    }
    assert all(case.blind and case.suite == "mentor_surprise_v1" for case in cases)
    assert len({case.question.casefold() for case in cases}) == len(cases)
    assert len({case.category for case in cases}) == len(cases)

    production_questions = {
        example.question.casefold() for example in examples.load_golden_dataset().questions
    }
    assert not production_questions.intersection(case.question.casefold() for case in cases)


def test_mentor_surprise_failures_are_promoted_to_a_deterministic_regression_gate():
    cases = select_cases(load_evaluation_dataset(), suite="mentor_surprise_regression_v1")
    assert {case.id for case in cases} == {
        "MENTOR-SURPRISE-003",
        "MENTOR-SURPRISE-005",
        "MENTOR-SURPRISE-007",
        *(f"MENTOR-SURPRISE-{index:03d}" for index in range(10, 15)),
        "MENTOR-SURPRISE-016",
        "MENTOR-SURPRISE-017",
        "MENTOR-SURPRISE-020",
        "MENTOR-SURPRISE-022",
        "MENTOR-SURPRISE-024",
        "MENTOR-SURPRISE-026",
    }
    assert all(not case.blind for case in cases)

    run = EvaluationRunner().run(
        suite="mentor_surprise_regression_v1",
        mode=EvaluationMode.SQL_GENERATION,
    )
    assert run.summary.passed == len(cases), [
        failure.model_dump() for result in run.results for failure in result.failures
    ]


def test_compositional_query_algebra_suite_is_a_deterministic_regression_gate():
    cases = select_cases(load_evaluation_dataset(), suite="compositional_query_algebra_v1")
    assert {case.id for case in cases} == {f"COMPOSE-ALG-{index:03d}" for index in range(1, 8)}

    run = EvaluationRunner().run(
        suite="compositional_query_algebra_v1",
        mode=EvaluationMode.SQL_GENERATION,
    )
    assert run.summary.passed == len(cases), [
        failure.model_dump() for result in run.results for failure in result.failures
    ]


def test_explicit_base_dataset_load_does_not_merge_colloquial_supplement():
    base_path = Path(__file__).parents[1] / "app" / "resources" / "evaluation_cases.json"
    base = load_evaluation_dataset(base_path)

    assert not any(case.id.startswith("COL-BLIND-") for case in base.cases)


def test_colloquial_guard_cases_follow_production_routing_contract():
    runner = EvaluationRunner()
    regression_cases = select_cases(load_evaluation_dataset(), suite="colloquial_regression_v2")
    assert {case.id for case in regression_cases} == {
        "COL-BLIND-001",
        "COL-BLIND-002",
        *(f"COL-BLIND-{index:03d}" for index in range(3, 9)),
        *(f"COL-BLIND-{index:03d}" for index in range(10, 13)),
        *(f"COL-BLIND-{index:03d}" for index in range(14, 18)),
        "COL-BLIND-018",
        "COL-BLIND-025",
        "COL-BLIND-027",
        "COL-BLIND-029",
        "COL-BLIND-030",
        "COL-BLIND-031",
        "COL-BLIND-034",
        *(f"COL-BLIND-{index:03d}" for index in range(36, 41)),
        *(f"COL-BLIND-{index:03d}" for index in range(43, 51)),
        "COL-BLIND-059",
        "COL-BLIND-061",
        "COL-BLIND-062",
        "COL-BLIND-064",
        "COL-BLIND-066",
        "COL-BLIND-068",
        "COL-BLIND-070",
        "COL-BLIND-076",
        "COL-BLIND-078",
    }
    assert all(not case.blind for case in regression_cases)
    for case_id in (
        "COL-BLIND-036",
        "COL-BLIND-037",
        "COL-BLIND-038",
        "COL-BLIND-039",
        "COL-BLIND-040",
        "COL-BLIND-030",
    ):
        result = runner.run(
            case_id=case_id,
            mode=EvaluationMode.SQL_GENERATION,
        ).results[0]
        assert result.passed, (case_id, result.failures)
        assert result.generated_sql is None


@pytest.mark.parametrize(
    "case_id",
    [
        "COL-BLIND-001",
        "COL-BLIND-002",
        *(f"COL-BLIND-{index:03d}" for index in range(3, 9)),
        *(f"COL-BLIND-{index:03d}" for index in range(10, 13)),
        *(f"COL-BLIND-{index:03d}" for index in range(14, 18)),
        "COL-BLIND-018",
        "COL-BLIND-025",
        "COL-BLIND-027",
        "COL-BLIND-029",
        "COL-BLIND-031",
        "COL-BLIND-034",
        *(f"COL-BLIND-{index:03d}" for index in range(43, 51)),
        "COL-BLIND-059",
        "COL-BLIND-061",
        "COL-BLIND-062",
        "COL-BLIND-064",
        "COL-BLIND-066",
        "COL-BLIND-068",
        "COL-BLIND-070",
        "COL-BLIND-076",
        "COL-BLIND-078",
    ],
)
def test_promoted_colloquial_analytical_regressions(case_id):
    result = (
        EvaluationRunner()
        .run(
            case_id=case_id,
            mode=EvaluationMode.SQL_GENERATION,
        )
        .results[0]
    )

    assert result.passed, (case_id, result.failures)
    assert result.sql_source == "deterministic"
    assert result.generated_sql


def test_routing_and_query_plan_scorer_acceptance_case():
    run = EvaluationRunner().run(
        suite="acceptance",
        case_id="E2E-RW-004",
        mode=EvaluationMode.PLANNER_ONLY,
    )
    assert run.results[0].passed
    assert run.results[0].plan_summary["analysis_type"] == "cohort_analysis"


@pytest.mark.parametrize("case_id", ["BLIND-CAS-006", "BLIND-CAS-008"])
def test_conversational_business_phrasing_regressions(case_id):
    """Common user wording must resolve to the catalog-backed deterministic path."""
    run = EvaluationRunner().run(
        case_id=case_id,
        mode=EvaluationMode.SQL_GENERATION,
    )

    assert run.results[0].passed, run.results[0].failures
    assert run.results[0].sql_source == "deterministic"


def test_sql_ast_ratio_period_cohort_and_raw_detail_scorers():
    runner = EvaluationRunner()
    ratio = runner.run(case_id="E2E-RW-007", mode=EvaluationMode.SQL_GENERATION)
    assert ratio.results[0].passed, ratio.results[0].failures
    period = runner.run(case_id="E2E-RW-006", mode=EvaluationMode.SQL_GENERATION)
    assert period.results[0].passed, period.results[0].failures
    cohort = runner.run(case_id="E2E-RW-004", mode=EvaluationMode.SQL_GENERATION)
    assert cohort.results[0].passed, cohort.results[0].failures


def test_raw_detail_detector_flags_detail_projection():
    case = [case for case in load_evaluation_dataset().cases if case.id == "E2E-RW-007"][0]
    stage = score_sql_semantics(
        case,
        "SELECT HastaAdi, COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu;",
    )
    assert any(
        failure.failure_code == FailureCode.RAW_DETAIL_INSTEAD_OF_AGGREGATE
        for failure in stage.failures
    )


def test_raw_detail_detector_allows_columns_inside_an_aggregate():
    """The lead-time metric AVG(CAST(DATEDIFF(day, CreatedDate, BaslangicTarihi)
    AS FLOAT)) references CreatedDate INSIDE an aggregate — that is not a raw
    detail leak and must not be flagged (2026-07-28)."""
    case = [case for case in load_evaluation_dataset().cases if case.id == "E2E-RW-007"][0]
    stage = score_sql_semantics(
        case,
        "SELECT AVG(CAST(DATEDIFF(day, CreatedDate, BaslangicTarihi) AS FLOAT)) "
        "AS appointment_lead_time_average FROM dbo.vw_RandevuRaporu;",
    )
    assert not any(
        failure.failure_code == FailureCode.RAW_DETAIL_INSTEAD_OF_AGGREGATE
        for failure in stage.failures
    )


def test_must_include_sql_and_must_not_include_sql_substring_assertions():
    """The free-form SQL-substring escape hatch (must_include_sql /
    must_not_include_sql) validates capability-specific SQL shapes."""
    case = [case for case in load_evaluation_dataset().cases if case.id == "EXP-THRESH-GT-001"][0]
    # Missing the required HAVING fragment → SQL_SHAPE_MISMATCH.
    missing = score_sql_semantics(
        case,
        "SELECT GenelRandevuBolumAdi, COUNT(*) AS appointment_count FROM dbo.vw_RandevuRaporu "
        "WHERE BaslangicTarihi >= '2024-01-01' GROUP BY GenelRandevuBolumAdi;",
    )
    assert any(f.failure_code == FailureCode.SQL_SHAPE_MISMATCH for f in missing.failures)
    # The real deterministic SQL for this case satisfies every fragment.
    from app.database_intelligence.models import ViewMetadata
    from app.planning.planner import QueryPlanner
    from app.services.deterministic_sql_builder import DeterministicSQLBuilder
    from app.services.query_analyzer import QueryAnalyzer

    view = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
    plan = QueryPlanner().build_plan(
        case.question,
        QueryAnalyzer().analyze(case.question),
        tables=[],
        views=[view],
    )
    built = DeterministicSQLBuilder().build(plan)
    ok = score_sql_semantics(case, built.sql, plan)
    assert not any(
        failure.failure_code == FailureCode.SQL_SHAPE_MISMATCH for failure in ok.failures
    ), ok.failures


def test_expert_suite_selects_only_expert_cases():
    from tools.evaluation.dataset import select_cases

    dataset = load_evaluation_dataset()
    expert = select_cases(dataset, suite="expert")
    assert expert, "expert suite must not be empty"
    assert all(case.suite == "expert" for case in expert)
    assert all(case.id.startswith("EXP-") for case in expert)


def test_result_contract_and_final_answer_checks():
    run = EvaluationRunner().run(
        case_id="E2E-RW-004",
        mode=EvaluationMode.MOCKED_EXECUTION,
    )
    result = run.results[0]
    assert any(stage.stage.value == "result_contract" for stage in result.stage_results)
    assert result.passed
    case = [case for case in load_evaluation_dataset().cases if case.id == "E2E-RW-004"][0]
    stage = score_final_answer(case, "generic error")
    assert any(f.failure_code == FailureCode.GENERIC_FINAL_ERROR for f in stage.failures)


def test_mock_period_labels_match_typed_result_contract():
    run = EvaluationRunner().run(
        suite="acceptance",
        mode=EvaluationMode.MOCKED_EXECUTION,
    )
    period_results = [result for result in run.results if result.case_id.startswith("E2E-RW-00")]
    assert period_results
    assert all(result.passed for result in period_results), [
        failure.model_dump() for result in period_results for failure in result.failures
    ]


def test_result_contract_accepts_negative_percentage_change():
    case = next(case for case in load_evaluation_dataset().cases if case.id == "E2E-RW-008")
    normalized = NormalizedResult(
        schema_name="PeriodComparisonResult",
        columns=[
            "current_period_count",
            "baseline_period_count",
            "absolute_change",
            "percentage_change",
        ],
        rows=[
            {
                "current_period_count": 94,
                "baseline_period_count": 100,
                "absolute_change": -6,
                "percentage_change": -6.0,
            }
        ],
    )
    assert score_result_contract(case, normalized).passed


def test_report_json_markdown_and_previous_comparison():
    tmp_path = Path(".tmp_pytest") / "evaluation_reports"
    tmp_path.mkdir(parents=True, exist_ok=True)
    runner = EvaluationRunner()
    first = runner.run(suite="acceptance", mode=EvaluationMode.PLANNER_ONLY)
    first.previous_comparison = {"status": "no_previous_run"}
    write_run_reports(first, tmp_path)
    second = runner.run(suite="acceptance", mode=EvaluationMode.PLANNER_ONLY)
    comparison = compare_with_previous(second, tmp_path)
    second.previous_comparison = comparison
    json_path, md_path = write_run_reports(second, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["run_id"] == second.run_id
    markdown = md_path.read_text(encoding="utf-8")
    assert "Run Summary" in markdown
    assert "Acceptance Case Sonuclari" in markdown
    assert comparison["previous_run_id"] == first.run_id


def test_cli_single_case_and_suite_run_no_write():
    assert main(["run", "--case", "E2E-RW-004", "--mode", "planner-only", "--no-write"]) == 0
    code = main(["run", "--suite", "acceptance", "--mode", "planner-only", "--no-write"])
    assert code in {0, 2, 3}


def test_live_db_skip_behavior(monkeypatch):
    monkeypatch.setattr("tools.evaluation.runner.settings.DATABASE_URL", "")
    run = EvaluationRunner().run(suite="live", mode=EvaluationMode.LIVE_DB)
    assert run.summary.skipped == run.summary.total_cases


def test_deterministic_three_run_stability():
    runner = EvaluationRunner()
    cases = [
        case
        for case in load_evaluation_dataset().cases
        if case.expected.sql_source == "deterministic"
    ][:50]
    assert len(cases) == 50
    snapshots = []
    for _ in range(3):
        run = runner.run(mode=EvaluationMode.SQL_GENERATION, limit=50, suite="deterministic")
        snapshots.append(
            [
                (
                    result.case_id,
                    result.sql_source,
                    result.result_contract,
                    result.generated_sql,
                )
                for result in run.results
            ]
        )
    assert snapshots[0] == snapshots[1] == snapshots[2]


def test_critical_acceptance_regression_exit_code():
    code = main(["run", "--case", "E2E-RW-003", "--mode", "sql-generation", "--no-write"])
    assert code in {0, 2}
