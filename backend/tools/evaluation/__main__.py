import argparse
import sys

from tools.evaluation.models import EvaluationMode
from tools.evaluation.report import (
    compare_with_previous,
    latest_run_path,
    load_run,
    write_run_reports,
)
from tools.evaluation.runner import EvaluationRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--suite", default="blind")
    run_parser.add_argument("--case", dest="case_id")
    run_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in EvaluationMode],
        default=EvaluationMode.SQL_GENERATION.value,
    )
    run_parser.add_argument("--limit", type=int)
    run_parser.add_argument("--no-write", action="store_true")

    report_parser = sub.add_parser("report")
    report_parser.add_argument("--latest", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "run":
        runner = EvaluationRunner()
        run = runner.run(
            suite=args.suite,
            case_id=args.case_id,
            mode=EvaluationMode(args.mode),
            limit=args.limit,
        )
        run.previous_comparison = compare_with_previous(run)
        if not args.no_write:
            json_path, md_path = write_run_reports(run)
            print(f"JSON report: {json_path}")
            print(f"Markdown report: {md_path}")
        print(
            f"cases={run.summary.total_cases} passed={run.summary.passed} "
            f"failed={run.summary.failed} skipped={run.summary.skipped}"
        )
        return _exit_code(run)

    if args.command == "report" and args.latest:
        path = latest_run_path()
        if path is None:
            print("No evaluation reports found.")
            return 1
        run = load_run(path)
        print(f"Latest run: {run.run_id}")
        print(
            f"cases={run.summary.total_cases} passed={run.summary.passed} "
            f"failed={run.summary.failed} skipped={run.summary.skipped}"
        )
        return 0
    return 1


def _exit_code(run) -> int:
    acceptance_failures = [
        result.case_id
        for result in run.results
        if result.case_id.startswith("E2E-RW-") and not result.passed and not result.skipped
    ]
    if acceptance_failures:
        return 2
    routing = run.summary.layer_accuracy.get("routing", 100.0)
    sql_generation = run.summary.layer_accuracy.get("sql_generation", 100.0)
    if routing < 95.0 or sql_generation < 95.0:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

