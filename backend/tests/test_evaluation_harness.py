import json
from pathlib import Path

import pytest
from tools.evaluation.__main__ import main
from tools.evaluation.dataset import load_evaluation_dataset, validate_evaluation_dataset
from tools.evaluation.models import EvaluationDataset, EvaluationMode, FailureCode
from tools.evaluation.report import compare_with_previous, write_run_reports
from tools.evaluation.runner import EvaluationRunner
from tools.evaluation.scorers import (
    score_final_answer,
    score_result_contract,
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


def test_routing_and_query_plan_scorer_acceptance_case():
    run = EvaluationRunner().run(
        suite="acceptance",
        case_id="E2E-RW-004",
        mode=EvaluationMode.PLANNER_ONLY,
    )
    assert run.results[0].passed
    assert run.results[0].plan_summary["analysis_type"] == "cohort_analysis"


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
        failure.model_dump()
        for result in period_results
        for failure in result.failures
    ]


def test_result_contract_accepts_negative_percentage_change():
    case = next(
        case
        for case in load_evaluation_dataset().cases
        if case.id == "E2E-RW-008"
    )
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
