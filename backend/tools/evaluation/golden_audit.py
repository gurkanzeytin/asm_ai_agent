"""Audit the golden question bank through planner, deterministic SQL, and validator.

This module never connects to the database. It verifies whether a documented
question is safe to use in an offline demo of the deterministic pipeline.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from app.database_intelligence.models import ViewMetadata
from app.planning.planner import QueryPlanner
from app.semantics.examples import GoldenExample, load_golden_dataset
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.services.query_analyzer import QueryAnalyzer
from app.sql_validator.validator import SQLValidator

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])


@dataclass(frozen=True)
class GoldenAuditResult:
    id: str
    question: str
    category: str
    passed: bool
    deterministic: bool
    failures: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _category(example: GoldenExample) -> str:
    return example.id.rsplit("-", 1)[0]


@lru_cache(maxsize=1)
def audit_golden_questions() -> tuple[GoldenAuditResult, ...]:
    analyzer = QueryAnalyzer()
    planner = QueryPlanner()
    builder = DeterministicSQLBuilder()
    validator = SQLValidator()
    results: list[GoldenAuditResult] = []

    for example in load_golden_dataset().questions:
        failures: list[str] = []
        warnings: list[str] = []
        ambiguity = analyzer.detect_ambiguity(example.question)
        clarification = ambiguity is not None
        if clarification != example.expected_plan.clarification_required:
            failures.append("clarification_mismatch")

        if clarification:
            results.append(
                GoldenAuditResult(
                    id=example.id,
                    question=example.question,
                    category=_category(example),
                    passed=not failures,
                    deterministic=False,
                    failures=tuple(failures),
                    warnings=tuple(warnings),
                )
            )
            continue

        analysis = analyzer.analyze(example.question)
        plan = planner.build_plan(example.question, analysis, tables=[], views=[VIEW])
        if plan.answerable != example.expected_plan.answerable:
            failures.append("answerability_mismatch")

        if not example.expected_plan.answerable:
            results.append(
                GoldenAuditResult(
                    id=example.id,
                    question=example.question,
                    category=_category(example),
                    passed=not failures,
                    deterministic=False,
                    failures=tuple(failures),
                    warnings=tuple(warnings),
                )
            )
            continue

        if example.analysis_type and plan.analysis_type != example.analysis_type:
            warnings.append("analysis_type_drift")
        if plan.metrics != example.metrics:
            warnings.append("metric_drift")
        if plan.dimensions != example.dimensions:
            warnings.append("dimension_drift")
        if not set(example.required_columns).issubset(plan.required_columns):
            warnings.append("required_columns_drift")

        built = builder.build(plan)
        deterministic = isinstance(built, DeterministicSQL)
        if not deterministic:
            failures.append("deterministic_sql_unavailable")
        else:
            validation = validator.validate(built.sql)
            if not validation.valid:
                failures.append("sql_validation_failed")
            for column in example.expected_sql_features.must_not_use_columns:
                if column in built.sql:
                    failures.append(f"forbidden_column:{column}")

        results.append(
            GoldenAuditResult(
                id=example.id,
                question=example.question,
                category=_category(example),
                passed=not failures,
                deterministic=deterministic,
                failures=tuple(dict.fromkeys(failures)),
                warnings=tuple(dict.fromkeys(warnings)),
            )
        )

    return tuple(results)


def summarize(results: Sequence[GoldenAuditResult]) -> str:
    passed = sum(result.passed for result in results)
    deterministic = sum(result.passed and result.deterministic for result in results)
    failure_counts = Counter(
        failure
        for result in results
        for failure in result.failures
    )
    warning_counts = Counter(
        warning
        for result in results
        for warning in result.warnings
    )
    lines = [
        f"questions={len(results)} passed={passed} failed={len(results) - passed} ",
        f"deterministic_demo_ready={deterministic}",
    ]
    lines.extend(f"{name}={count}" for name, count in failure_counts.most_common())
    lines.extend(f"warning:{name}={count}" for name, count in warning_counts.most_common())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", choices=("passing", "failing", "all"), default="failing")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit code when any golden question fails the audit.",
    )
    args = parser.parse_args(argv)

    results = audit_golden_questions()
    print(summarize(results))
    selected = [
        result
        for result in results
        if args.show == "all"
        or (args.show == "passing" and result.passed)
        or (args.show == "failing" and not result.passed)
    ]
    if args.category:
        selected = [result for result in selected if result.category == args.category]
    if args.limit is not None:
        selected = selected[: args.limit]
    for result in selected:
        print(
            "\t".join(
                (
                    result.id,
                    "PASS" if result.passed else "FAIL",
                    "deterministic" if result.deterministic else "no-sql",
                    ",".join(result.failures),
                    ",".join(result.warnings),
                    result.question,
                )
            )
        )
    return 1 if args.strict and not all(result.passed for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
