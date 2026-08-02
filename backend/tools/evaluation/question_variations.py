"""Generate unseen catalog-driven questions and audit the offline SQL pipeline."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

from app.database_intelligence.models import ViewMetadata
from app.planning.planner import QueryPlanner
from app.semantics import catalog
from app.semantics.view_mapping import fold
from app.services.answerability import AnswerabilityGuard
from app.services.deterministic_sql_builder import (
    DeterministicSQL,
    DeterministicSQLBuilder,
)
from app.services.query_analyzer import QueryAnalyzer
from app.services.schema_capability import SchemaCapabilityService
from app.sql_validator.validator import SQLValidator

VIEW = ViewMetadata(name="dbo.vw_RandevuRaporu", columns=[])
_PERIODS = (
    ("all_time", "", False),
    ("year_2024", "2024 yılında ", True),
    ("previous_year", "geçen yıl ", True),
)
_MULTI_PERIOD_PERIODS = (
    ("years_2023_2024", "2023 ve 2024 yıllarında ", True),
    ("years_2024_2025", "2024 ve 2025 yıllarında ", True),
    ("months_may_june_2024", "Mayıs 2024 ve Haziran 2024 dönemlerinde ", True),
)
_SCALAR_TEMPLATES = (
    "{period}{metric} nedir?",
    "{period}{metric} için rakamı verir misin?",
    "{period}{metric} ne durumda?",
)
_DIMENSION_TEMPLATES = (
    "{period}{dimension} bazında {metric} göster.",
    "{period}{metric}, {dimension} kırılımında nasıl?",
    "{period}{dimension} tarafında {metric} dağılımı nedir?",
)


@dataclass(frozen=True)
class GeneratedQuestion:
    id: str
    question: str
    family: str
    expected_metric: str | None = None
    expected_dimension: str | None = None
    expected_columns: tuple[str, ...] = field(default_factory=tuple)
    expects_date: bool = False
    expects_clarification: bool = False
    must_not_select: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class VariationAuditResult:
    case: GeneratedQuestion
    passed: bool
    deterministic: bool
    failures: tuple[str, ...] = field(default_factory=tuple)


def _phrases(primary: str, synonyms: Sequence[str], *, limit: int = 2) -> list[str]:
    candidates = [primary, *synonyms]
    output: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip().lower()
        if normalized and normalized not in output:
            output.append(normalized)
        if len(output) >= limit:
            break
    return output


def _dimension_phrases(spec: catalog.ColumnSpec, *, limit: int = 2) -> list[str]:
    """Choose phrases that keep their catalog identity in grouping grammar.

    A bare alias can be valid for one column but become a more specific column
    when followed by ``kırılımında`` (for example ``doktor``: source-name alias
    when bare, DoktorId when explicitly grouped). Such a phrase is useful in an
    ambiguity suite, but not as the sole expected identity in this matrix.
    """
    stable: list[str] = []
    for phrase in _phrases(spec.business_name, spec.synonyms, limit=len(spec.synonyms) + 1):
        grouped = catalog.match_dimensions(fold(f"{phrase} kırılımında"))
        if grouped == [spec.column]:
            stable.append(phrase)
        if len(stable) >= limit:
            return stable
    return stable or _phrases(spec.business_name, spec.synonyms, limit=limit)


def _periods_for_metric(metric: catalog.MetricSpec) -> tuple[tuple[str, str, bool], ...]:
    if metric.id == "multi_period_patient_overlap_count":
        return _MULTI_PERIOD_PERIODS
    return _PERIODS


@lru_cache(maxsize=1)
def generate_question_variations() -> tuple[GeneratedQuestion, ...]:
    """Builds stable questions from catalogs without adding them to few-shot retrieval."""
    column_catalog = catalog.load_column_catalog()
    metric_catalog = catalog.load_metric_catalog()
    column_by_id = {column.column: column for column in column_catalog.columns}
    cases: list[GeneratedQuestion] = []

    for metric in metric_catalog.metrics:
        periods = _periods_for_metric(metric)
        metric_phrases = _phrases(metric.name, metric.synonyms)
        for phrase_index, metric_phrase in enumerate(metric_phrases, start=1):
            for period_id, period, expects_date in periods:
                template = _SCALAR_TEMPLATES[(phrase_index - 1) % len(_SCALAR_TEMPLATES)]
                cases.append(
                    GeneratedQuestion(
                        id=f"VAR-METRIC-{metric.id}-{phrase_index}-{period_id}",
                        question=template.format(period=period, metric=metric_phrase),
                        family="metric_scalar",
                        expected_metric=metric.id,
                        expected_columns=tuple(metric.required_columns),
                        expects_date=expects_date,
                        expects_clarification=(
                            metric.status == "requires_verified_mapping"
                        ),
                    )
                )

        compatible_dimensions = [
            dimension
            for dimension in metric.compatible_dimensions
            if dimension in column_by_id
            and column_by_id[dimension].groupable
            # DoktorId is the stable identity while GenelRandevuKaynakAdi is
            # its display/source alias in this view. Crossing a doctor-fixed
            # metric with that alias generates the self-contradictory
            # "doktor bazında ... hekim kırılımında" rather than a new axis.
            and not (
                metric.fixed_dimension == "DoktorId"
                and dimension == "GenelRandevuKaynakAdi"
            )
        ][:3]
        for dimension in compatible_dimensions:
            dimension_spec = column_by_id[dimension]
            dimension_phrases = _dimension_phrases(dimension_spec)
            for phrase_index, dimension_phrase in enumerate(dimension_phrases, start=1):
                for period_id, period, expects_date in periods[:2]:
                    template = _DIMENSION_TEMPLATES[
                        (phrase_index - 1) % len(_DIMENSION_TEMPLATES)
                    ]
                    cases.append(
                        GeneratedQuestion(
                            id=(
                                f"VAR-DIM-{metric.id}-{dimension}-"
                                f"{phrase_index}-{period_id}"
                            ),
                            question=template.format(
                                period=period,
                                dimension=dimension_phrase,
                                metric=metric.name.lower(),
                            ),
                            family="metric_dimension",
                            expected_metric=metric.id,
                            expected_dimension=dimension,
                            expected_columns=tuple(
                                dict.fromkeys([*metric.required_columns, dimension])
                            ),
                            expects_date=expects_date,
                            expects_clarification=(
                                metric.status == "requires_verified_mapping"
                            ),
                        )
                    )

    for column in column_catalog.columns:
        cases.append(
            GeneratedQuestion(
                id=f"VAR-COLUMN-{column.column}",
                question=(
                    f"{column.business_name} alanını kullanarak hangi analizi yapabilirsin?"
                ),
                family="column_capability",
                expected_columns=(column.column,),
            )
        )
        if column.pii or not column.selectable:
            cases.append(
                GeneratedQuestion(
                    id=f"VAR-PRIVACY-{column.column}",
                    question=f"Tüm {column.business_name.lower()} değerlerini ham listele.",
                    family="privacy_guard",
                    must_not_select=(column.column,),
                )
            )

    return tuple(cases)


@lru_cache(maxsize=1)
def audit_question_variations() -> tuple[VariationAuditResult, ...]:
    analyzer = QueryAnalyzer()
    answerability = AnswerabilityGuard(query_analyzer=analyzer)
    planner = QueryPlanner()
    builder = DeterministicSQLBuilder()
    validator = SQLValidator()
    capability_service = SchemaCapabilityService()
    results: list[VariationAuditResult] = []

    for case in generate_question_variations():
        failures: list[str] = []
        if case.family == "column_capability":
            capability = capability_service.answer(case.question)
            if capability is None:
                failures.append("capability_answer_missing")
            elif capability.column not in case.expected_columns:
                failures.append("capability_column_mismatch")
            results.append(
                VariationAuditResult(
                    case=case,
                    passed=not failures,
                    deterministic=False,
                    failures=tuple(failures),
                )
            )
            continue
        ambiguity = analyzer.detect_ambiguity(case.question)
        if case.expects_clarification:
            passed = (
                ambiguity is not None
                and ambiguity.matched_phrase == "unverified_metric_mapping"
            )
            results.append(
                VariationAuditResult(
                    case=case,
                    passed=passed,
                    deterministic=False,
                    failures=() if passed else ("expected_clarification_missing",),
                )
            )
            continue
        if case.must_not_select and ambiguity is not None:
            results.append(
                VariationAuditResult(case=case, passed=True, deterministic=False)
            )
            continue
        if ambiguity is not None:
            failures.append("unexpected_clarification")
            results.append(
                VariationAuditResult(
                    case=case,
                    passed=False,
                    deterministic=False,
                    failures=tuple(failures),
                )
            )
            continue

        verdict = answerability.assess(case.question)
        if not verdict.answerable:
            if case.must_not_select:
                results.append(
                    VariationAuditResult(case=case, passed=True, deterministic=False)
                )
                continue
            failures.append("out_of_scope")

        analysis = analyzer.analyze(case.question)
        plan = planner.build_plan(case.question, analysis, tables=[], views=[VIEW])
        if not plan.answerable:
            failures.append("plan_not_answerable")
        if case.expected_metric and not _metric_satisfied(case.expected_metric, plan):
            failures.append("metric_mismatch")
        if case.expected_dimension and case.expected_dimension not in plan.dimensions:
            failures.append("dimension_mismatch")
        if case.expected_columns and not set(case.expected_columns).issubset(
            plan.required_columns
        ):
            failures.append("required_column_missing")
        if case.expects_date and not plan.date_filters:
            failures.append("date_missing")

        built = builder.build(plan)
        deterministic = isinstance(built, DeterministicSQL)
        if not deterministic:
            if case.must_not_select:
                failures.append("privacy_unverified_llm_fallback")
            else:
                failures.append("deterministic_unavailable")
        else:
            validation = validator.validate(built.sql)
            if not validation.valid:
                failures.append("invalid_sql")
            select_clause = built.sql.upper().split("FROM", 1)[0]
            for column in case.must_not_select:
                if column.upper() in select_clause:
                    failures.append(f"privacy_violation:{column}")

        results.append(
            VariationAuditResult(
                case=case,
                passed=not failures,
                deterministic=deterministic,
                failures=tuple(dict.fromkeys(failures)),
            )
        )

    return tuple(results)


def _metric_satisfied(expected_metric: str, plan: object) -> bool:
    """Accept catalog-equivalent canonical count + fixed-dimension plans."""
    metrics = getattr(plan, "metrics", [])
    dimensions = getattr(plan, "dimensions", [])
    if expected_metric in metrics:
        return True
    metric = catalog.load_metric_catalog().by_id().get(expected_metric)
    return bool(
        metric
        and metric.formula_type == "count_rows_grouped"
        and metric.formula == "COUNT(*)"
        and metric.fixed_dimension
        and "appointment_count" in metrics
        and metric.fixed_dimension in dimensions
    )


def summarize(results: Sequence[VariationAuditResult]) -> str:
    passed = sum(result.passed for result in results)
    deterministic = sum(result.passed and result.deterministic for result in results)
    failure_counts = Counter(
        failure for result in results for failure in result.failures
    )
    family_counts = Counter(result.case.family for result in results)
    lines = [
        f"questions={len(results)} passed={passed} failed={len(results) - passed}",
        f"deterministic_passed={deterministic}",
        "families=" + ",".join(f"{key}:{value}" for key, value in sorted(family_counts.items())),
    ]
    lines.extend(f"failure:{name}={count}" for name, count in failure_counts.most_common())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", choices=("passing", "failing", "all"), default="failing")
    parser.add_argument("--family")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    results = audit_question_variations()
    print(summarize(results))
    selected = [
        result
        for result in results
        if args.show == "all"
        or (args.show == "passing" and result.passed)
        or (args.show == "failing" and not result.passed)
    ]
    if args.family:
        selected = [result for result in selected if result.case.family == args.family]
    if args.limit is not None:
        selected = selected[: args.limit]
    for result in selected:
        print(
            "\t".join(
                (
                    result.case.id,
                    "PASS" if result.passed else "FAIL",
                    result.case.family,
                    ",".join(result.failures),
                    result.case.question,
                )
            )
        )
    return 1 if args.strict and not all(result.passed for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
