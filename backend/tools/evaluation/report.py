import json

# ruff: noqa: E501
from collections import Counter
from pathlib import Path

from tools.evaluation.models import EvaluationRun

RESULTS_DIR = Path("evaluation") / "results"


def write_run_reports(run: EvaluationRun, output_dir: Path | None = None) -> tuple[Path, Path]:
    directory = output_dir or RESULTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{run.run_id}.json"
    md_path = directory / f"{run.run_id}.md"
    json_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(build_markdown(run), encoding="utf-8")
    return json_path, md_path


def latest_run_path(output_dir: Path | None = None) -> Path | None:
    directory = output_dir or RESULTS_DIR
    if not directory.exists():
        return None
    files = sorted(directory.glob("*.json"))
    return files[-1] if files else None


def load_run(path: Path) -> EvaluationRun:
    return EvaluationRun(**json.loads(path.read_text(encoding="utf-8")))


def compare_with_previous(run: EvaluationRun, output_dir: Path | None = None) -> dict:
    previous_path = latest_run_path(output_dir)
    if previous_path is None:
        return {"status": "no_previous_run"}
    previous = load_run(previous_path)
    current_failures = set(_failed_case_ids(run))
    previous_failures = set(_failed_case_ids(previous))
    return {
        "previous_run_id": previous.run_id,
        "passed_delta": run.summary.passed - previous.summary.passed,
        "failed_delta": run.summary.failed - previous.summary.failed,
        "new_failure_types": sorted(set(run.summary.failure_counts) - set(previous.summary.failure_counts)),
        "resolved_failure_types": sorted(set(previous.summary.failure_counts) - set(run.summary.failure_counts)),
        "regression_case_ids": sorted(current_failures - previous_failures),
        "resolved_case_ids": sorted(previous_failures - current_failures),
        "p95_delta_ms": run.summary.p95_ms - previous.summary.p95_ms,
    }


def build_markdown(run: EvaluationRun) -> str:
    summary = run.summary
    lines = [
        "# Evaluation Run Report",
        "",
        "## 1. Run Summary",
        f"- Run ID: `{run.run_id}`",
        f"- Generated: `{run.generated_at}`",
        f"- Mode: `{run.mode.value}`",
        f"- Suite: `{run.suite}`",
        "",
        "## 2. Suite ve Environment",
        f"- SQL dialect: `{run.environment.get('sql_dialect')}`",
        f"- Database provider: `{run.environment.get('database_provider')}`",
        f"- Live DB available: `{run.environment.get('live_db_available')}`",
        "",
        "## 3. Toplam Case",
        f"- Total: {summary.total_cases}",
        "",
        "## 4. Passed / Failed / Skipped",
        f"- Passed: {summary.passed}",
        f"- Failed: {summary.failed}",
        f"- Skipped: {summary.skipped}",
        "",
        "## 5. Layer Accuracy",
    ]
    for layer, accuracy in summary.layer_accuracy.items():
        lines.append(f"- {layer}: {accuracy}%")
    lines.extend(
        [
            "",
            "## 6. Routing Accuracy",
            f"- {summary.layer_accuracy.get('routing', 0.0)}%",
            "",
            "## 7. QueryPlan Accuracy",
            f"- {summary.layer_accuracy.get('query_plan', 0.0)}%",
            "",
            "## 8. Deterministic SQL Success",
            f"- {summary.layer_accuracy.get('sql_generation', 0.0)}%",
            "",
            "## 9. LLM Fallback Success",
            "- Optional benchmark; skipped unless LLM mode is explicitly used.",
            "",
            "## 10. Execution Success",
            f"- {summary.layer_accuracy.get('execution', 0.0)}%",
            "",
            "## 11. Result Contract Success",
            f"- {summary.layer_accuracy.get('result_contract', 0.0)}%",
            "",
            "## 12. Final Answer Success",
            f"- {summary.layer_accuracy.get('final_answer', 0.0)}%",
            "",
            "## 13. Failure Taxonomy",
        ]
    )
    if summary.failure_counts:
        for code, count in summary.failure_counts.items():
            lines.append(f"- {code}: {count}")
    else:
        lines.append("- No failures")
    lines.extend(["", "## 14. En Sik 10 Hata"])
    for code, count in list(summary.failure_counts.items())[:10]:
        lines.append(f"- {code}: {count}")
    if not summary.failure_counts:
        lines.append("- No failures")
    lines.extend(["", "## 15. En Yavas 10 Soru"])
    slowest = sorted(run.results, key=lambda result: result.total_ms, reverse=True)[:10]
    for result in slowest:
        lines.append(f"- {result.case_id}: {result.total_ms:.1f} ms")
    lines.extend(["", "## 16. Acceptance Case Sonuclari"])
    for result in [r for r in run.results if r.case_id.startswith("E2E-RW-")]:
        status = "SKIP" if result.skipped else ("PASS" if result.passed else "FAIL")
        failed_layers = [
            stage.stage.value for stage in result.stage_results if stage.failures
        ]
        lines.append(
            f"- {result.case_id}: {status}; sql_source={result.sql_source}; "
            f"contract={result.result_contract}; failed_layers={failed_layers or 'none'}"
        )
    lines.extend(
        [
            "",
            "## 17. Regression Karsilastirmasi",
            json.dumps(run.previous_comparison or {"status": "not_computed"}, ensure_ascii=False),
            "",
            "## 18. Onerilen Sonraki Duzeltmeler",
        ]
    )
    lines.extend(_recommendations(run))
    return "\n".join(lines)


def _failed_case_ids(run: EvaluationRun) -> list[str]:
    return [result.case_id for result in run.results if not result.passed and not result.skipped]


def _recommendations(run: EvaluationRun) -> list[str]:
    counter = Counter(run.summary.failure_counts)
    if not counter:
        return ["- No immediate evaluation failures in this run."]
    top = counter.most_common(1)[0][0]
    return [f"- Prioritize fixing `{top}` failures first."]
