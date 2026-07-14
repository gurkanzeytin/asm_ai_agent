"""Unit tests for the PERF-001 benchmark tool (no LLM, no network)."""

import csv
import json
from pathlib import Path

import pytest

from tools.benchmark.dataset import DatasetError, dataset_categories, load_dataset
from tools.benchmark.metrics import (
    ModelSummary,
    Outcome,
    QuestionRun,
    Reason,
    classify,
    percentile,
    rank_models,
    summarize_model,
)
from tools.benchmark.report import (
    build_markdown,
    build_recommendation,
    summarize_all,
    write_csv,
    write_json,
)

DATASET_PATH = Path(__file__).resolve().parents[2] / "benchmark" / "questions.json"


def _run(**overrides) -> QuestionRun:
    base = dict(
        model="test-model",
        question_id=1,
        category="count",
        question="Kaç doktor var?",
        generated_sql="SELECT COUNT(*) FROM doktorlar;",
        execution_success=True,
        rows_returned=1,
        analytics_generated=True,
        insight_generated=True,
        report_generated=True,
        total_ms=1000.0,
        sql_generation_ms=500.0,
    )
    base.update(overrides)
    run = QuestionRun(**base)
    outcome, reason = classify(run)
    run.outcome, run.reason = outcome.value, reason.value
    return run


# ── Dataset loading ───────────────────────────────────────────────────────────


def test_dataset_loads_with_50_plus_questions_and_expected_categories():
    questions = load_dataset(DATASET_PATH)
    assert len(questions) >= 50
    categories = set(dataset_categories(questions))
    assert {
        "natural_language", "listing", "count", "comparison", "trend",
        "analytics", "ranking", "date_filtering", "ambiguous", "graceful_failure",
    } <= categories
    assert len({q.id for q in questions}) == len(questions)  # unique ids


def test_dataset_category_filter_and_limit():
    trend = load_dataset(DATASET_PATH, categories=["trend"], limit=2)
    assert len(trend) == 2
    assert all(q.category == "trend" for q in trend)


def test_dataset_missing_file_raises():
    with pytest.raises(DatasetError):
        load_dataset(Path("does/not/exist.json"))


def test_dataset_rejects_duplicate_ids(tmp_path):
    bad = tmp_path / "questions.json"
    bad.write_text(json.dumps({"questions": [
        {"id": 1, "category": "count", "question": "a"},
        {"id": 1, "category": "count", "question": "b"},
    ]}), encoding="utf-8")
    with pytest.raises(DatasetError):
        load_dataset(bad)


# ── Classification ────────────────────────────────────────────────────────────


def test_classify_success():
    run = _run()
    assert run.outcome == Outcome.SUCCESS
    assert run.reason == Reason.OK


def test_classify_no_sql_is_generation_failure():
    run = _run(generated_sql=None, execution_success=False, rows_returned=0)
    assert run.outcome == Outcome.FAILED
    assert run.reason == Reason.SQL_GENERATION_FAILED


def test_classify_execution_failure_is_invalid_sql():
    run = _run(execution_success=False)
    assert run.outcome == Outcome.FAILED
    assert run.reason == Reason.INVALID_SQL


def test_classify_empty_result_is_partial():
    run = _run(rows_returned=0)
    assert run.outcome == Outcome.PARTIAL
    assert run.reason == Reason.NO_RESULTS


def test_classify_wrong_entity():
    run = _run(
        question="Randevuları listele",
        category="listing",
        generated_sql="SELECT * FROM doktorlar;",
    )
    assert run.outcome == Outcome.PARTIAL
    assert run.reason == Reason.WRONG_ENTITY


def test_classify_trend_without_analytics_is_partial():
    run = _run(category="trend", analytics_generated=False)
    assert run.outcome == Outcome.PARTIAL
    assert run.reason == Reason.NO_ANALYTICS


def test_classify_graceful_categories_succeed_without_crash():
    run = _run(
        category="graceful_failure",
        generated_sql=None,
        execution_success=False,
        rows_returned=0,
        errors=["GenerateSQLNode failed: ..."],
    )
    assert run.outcome == Outcome.SUCCESS

    crashed = _run(category="ambiguous", exception="RuntimeError: boom")
    assert crashed.outcome == Outcome.FAILED
    assert crashed.reason == Reason.PIPELINE_FAILURE


def test_classify_timeout():
    run = _run(
        generated_sql=None,
        execution_success=False,
        report_generated=False,
        llm_timeouts=1,
        rows_returned=0,
    )
    assert run.outcome == Outcome.FAILED
    assert run.reason == Reason.TIMEOUT


# ── Aggregation ───────────────────────────────────────────────────────────────


def test_percentile_nearest_rank():
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 95) == 95.0
    assert percentile([], 95) == 0.0
    assert percentile([7.0], 95) == 7.0


def test_summarize_model_metrics():
    runs = [
        _run(total_ms=1000.0, prompt_tokens=100, completion_tokens=50),
        _run(total_ms=3000.0, retry_count=1, question_id=2),
        _run(total_ms=2000.0, rows_returned=0, question_id=3),  # PARTIAL
        _run(total_ms=4000.0, execution_success=False, question_id=4),  # FAILED
    ]
    summary = summarize_model("test-model", runs)

    assert summary.total_questions == 4
    assert summary.success == 2
    assert summary.partial == 1
    assert summary.failed == 1
    assert summary.success_rate == 50.0
    assert summary.avg_latency_ms == 2500.0
    assert summary.median_latency_ms == 2500.0
    assert summary.p95_latency_ms == 4000.0
    assert summary.retry_rate == 25.0
    assert summary.failure_reasons[Reason.NO_RESULTS.value] == 1
    assert summary.failure_reasons[Reason.INVALID_SQL.value] == 1
    assert 0.0 <= summary.overall_score <= 1.0


def test_rank_models_orders_by_overall_score():
    fast_accurate = summarize_model("a", [_run(total_ms=1000.0)])
    slow_failing = summarize_model(
        "b", [_run(total_ms=90000.0, execution_success=False)]
    )
    ranked = rank_models([slow_failing, fast_accurate])
    assert [s.model for s in ranked] == ["a", "b"]


# ── Report generation ─────────────────────────────────────────────────────────


def _two_model_runs() -> list[QuestionRun]:
    return [
        _run(model="model-a", total_ms=2000.0),
        _run(model="model-a", total_ms=3000.0, question_id=2, category="trend"),
        _run(model="model-b", total_ms=9000.0, execution_success=False),
        _run(model="model-b", total_ms=8000.0, question_id=2, category="trend"),
    ]


def test_markdown_report_contains_required_tables():
    summaries = summarize_all(_two_model_runs())
    markdown = build_markdown(summaries, skipped_models=["mistral"], total_duration_s=120.0)

    assert "## Overall Ranking" in markdown
    assert "## Performance Breakdown" in markdown
    assert "## Accuracy Breakdown" in markdown
    assert "## Failure Analysis" in markdown
    assert "## Resource Usage" in markdown
    assert "## Recommendation" in markdown
    assert "## Charts" in markdown
    assert "| Rank | Model | Success Rate |" in markdown
    assert "model-a" in markdown and "model-b" in markdown
    assert "Skipped models (not installed): mistral" in markdown
    assert "../charts/avg_latency.png" in markdown


def test_recommendation_is_deterministic_and_grounded():
    summaries = summarize_all(_two_model_runs())
    block = "\n".join(build_recommendation(rank_models(summaries)))
    assert "**Fastest Model:** model-a" in block
    assert "**Most Accurate Model:** model-a" in block
    assert "**Recommended Production Model:** model-a" in block
    assert "**Reason:**" in block


# ── CSV / JSON generation ─────────────────────────────────────────────────────


def test_csv_output_round_trips(tmp_path):
    runs = _two_model_runs()
    path = tmp_path / "benchmark.csv"
    write_csv(runs, path)

    with open(path, encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(runs)
    assert rows[0]["model"] == "model-a"
    assert rows[0]["outcome"] == "SUCCESS"
    assert "total_ms" in rows[0]


def test_json_output_contains_summaries_and_runs(tmp_path):
    runs = _two_model_runs()
    summaries = summarize_all(runs)
    path = tmp_path / "benchmark.json"
    write_json(runs, summaries, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["runs"]) == len(runs)
    assert {s["model"] for s in payload["summaries"]} == {"model-a", "model-b"}
    assert payload["generated_at"]
