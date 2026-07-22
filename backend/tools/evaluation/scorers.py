from __future__ import annotations

# ruff: noqa: E501
import re
import time
from numbers import Number
from typing import Any

import sqlglot
import sqlglot.expressions as exp
from tools.evaluation.models import (
    EvaluationCase,
    EvaluationStage,
    FailureCode,
    FailureRecord,
    StageResult,
)

from app.analytics.result_contracts import NormalizedResult
from app.planning.models import QueryPlan
from app.sql_validator.models import SQLValidationResult

# TCKimlikNo/PasaportNo/HastaGSM no longer exist in the view; SQL using them
# fails unknown-column validation before any raw-detail scoring applies.
RAW_DETAIL_COLUMNS = {
    "HastaAdi",
    "HastaSoyadi",
    "CreatedDate",
    "BitisTarihi",
}
GENERIC_ERROR_MARKERS = (
    "generic error",
    "bir hata olustu",
    "hata olustu",
    "failed",
    "exception",
)


def score_routing(case: EvaluationCase, *, clarification_required: bool) -> StageResult:
    start = time.perf_counter()
    failures: list[FailureRecord] = []
    if case.expected.clarification_required and not clarification_required:
        failures.append(_failure(case, EvaluationStage.ROUTING, FailureCode.CLARIFICATION_MISSED, True, False))
    if not case.expected.clarification_required and clarification_required:
        failures.append(
            _failure(case, EvaluationStage.ROUTING, FailureCode.CLARIFICATION_UNNECESSARY, False, True)
        )
    return _stage(EvaluationStage.ROUTING, failures, start)


def score_query_plan(case: EvaluationCase, plan: QueryPlan | None) -> StageResult:
    start = time.perf_counter()
    failures: list[FailureRecord] = []
    if plan is None:
        if case.expected.clarification_required:
            return _stage(EvaluationStage.QUERY_PLAN, failures, start)
        failures.append(_failure(case, EvaluationStage.QUERY_PLAN, FailureCode.PLAN_NOT_ANSWERABLE, "plan", None))
        return _stage(EvaluationStage.QUERY_PLAN, failures, start)

    expected = case.expected
    if plan.answerable != expected.answerable:
        failures.append(
            _failure(case, EvaluationStage.QUERY_PLAN, FailureCode.PLAN_NOT_ANSWERABLE, expected.answerable, plan.answerable, plan)
        )
    if expected.analysis_type and plan.analysis_type != expected.analysis_type:
        failures.append(
            _failure(case, EvaluationStage.QUERY_PLAN, FailureCode.WRONG_ANALYSIS_TYPE, expected.analysis_type, plan.analysis_type, plan)
        )
    missing_metrics = set(expected.metrics) - set(plan.metrics)
    if missing_metrics:
        failures.append(
            _failure(case, EvaluationStage.QUERY_PLAN, FailureCode.WRONG_METRIC, sorted(expected.metrics), sorted(plan.metrics), plan)
        )
    if expected.dimensions and not (set(expected.dimensions) & set(plan.dimensions)):
        failures.append(
            _failure(case, EvaluationStage.QUERY_PLAN, FailureCode.WRONG_DIMENSION, expected.dimensions, plan.dimensions, plan)
        )
    if expected.baseline_period and plan.baseline_period != expected.baseline_period:
        failures.append(
            _failure(case, EvaluationStage.QUERY_PLAN, FailureCode.WRONG_BASELINE, expected.baseline_period, plan.baseline_period, plan)
        )
    if expected.cohort and expected.cohort not in (plan.cohort or ""):
        failures.append(
            _failure(case, EvaluationStage.QUERY_PLAN, FailureCode.WRONG_COHORT, expected.cohort, plan.cohort, plan)
        )
    if expected.minimum_sample_size and plan.minimum_sample_size != expected.minimum_sample_size:
        failures.append(
            _failure(case, EvaluationStage.QUERY_PLAN, FailureCode.WRONG_DATE_CONTEXT, expected.minimum_sample_size, plan.minimum_sample_size, plan)
        )
    return _stage(EvaluationStage.QUERY_PLAN, failures, start)


def score_sql_generation(
    case: EvaluationCase,
    *,
    sql: str | None,
    sql_source: str | None,
    result_contract: str | None,
    aliases: list[str],
    validation: SQLValidationResult | None,
    plan: QueryPlan | None = None,
) -> StageResult:
    start = time.perf_counter()
    failures: list[FailureRecord] = []
    expected = case.expected
    if expected.sql_source and sql_source != expected.sql_source:
        failures.append(
            _failure(
                case,
                EvaluationStage.SQL_GENERATION,
                FailureCode.DETERMINISTIC_BUILDER_NOT_SELECTED,
                expected.sql_source,
                sql_source,
                plan,
                sql,
            )
        )
    if sql and validation and not validation.valid:
        failures.append(
            _failure(case, EvaluationStage.SQL_GENERATION, FailureCode.INVALID_SQL, "valid", validation.reason, plan, sql)
        )
    elif sql:
        try:
            sqlglot.parse_one(sql, read="tsql")
        except Exception as error:
            failures.append(
                _failure(case, EvaluationStage.SQL_GENERATION, FailureCode.INVALID_SQL, "parseable", str(error), plan, sql, type(error).__name__)
            )
    if expected.result_contract and result_contract != expected.result_contract:
        failures.append(
            _failure(
                case,
                EvaluationStage.SQL_GENERATION,
                FailureCode.RESULT_CONTRACT_MISMATCH,
                expected.result_contract,
                result_contract,
                plan,
                sql,
            )
        )
    missing_aliases = _expected_aliases(expected.result_contract, aliases)
    if missing_aliases:
        failures.append(
            _failure(case, EvaluationStage.SQL_GENERATION, FailureCode.RESULT_ALIAS_MISSING, missing_aliases, aliases, plan, sql)
        )
    return _stage(EvaluationStage.SQL_GENERATION, failures, start)


def score_sql_semantics(case: EvaluationCase, sql: str | None, plan: QueryPlan | None = None) -> StageResult:
    start = time.perf_counter()
    failures: list[FailureRecord] = []
    if not sql:
        if case.expected.sql_source:
            failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.INVALID_SQL, "sql", None, plan))
        return _stage(EvaluationStage.SQL_SEMANTICS, failures, start)
    try:
        tree = sqlglot.parse_one(sql, read="tsql")
    except Exception as error:
        failures.append(
            _failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.INVALID_SQL, "parseable", str(error), plan, sql, type(error).__name__)
        )
        return _stage(EvaluationStage.SQL_SEMANTICS, failures, start)

    tables = {table.sql(dialect="tsql").replace("[", "").replace("]", "") for table in tree.find_all(exp.Table)}
    physical = {table for table in tables if table.lower() not in {"group_counts", "ranked"}}
    if physical and not any("vw_RandevuRaporu" in table for table in physical):
        failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.WRONG_VIEW, "dbo.vw_RandevuRaporu", sorted(physical), plan, sql))

    sql_lower = sql.lower()
    for column in case.sql_requirements.must_use_columns:
        if not _has_column(tree, column) and column.lower() not in sql_lower:
            failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.UNKNOWN_COLUMN, column, "missing", plan, sql))
    if not case.expected.raw_detail_allowed and _raw_detail_projection(tree):
        failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.RAW_DETAIL_INSTEAD_OF_AGGREGATE, "aggregate", "detail columns", plan, sql))
    if "group_by" in case.sql_requirements.must_include_features and not tree.find(exp.Group):
        failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.MISSING_GROUP_BY, "GROUP BY", None, plan, sql))
    if "null_safe_division" in case.sql_requirements.must_include_features and "/" in sql and "nullif" not in sql_lower:
        failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.WRONG_RATIO_DENOMINATOR, "NULLIF", None, plan, sql))
    if "current_period" in case.sql_requirements.must_include_features and "current_" not in sql_lower:
        failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.MISSING_PERIOD_PAIR, "current period", None, plan, sql))
    if "baseline_period" in case.sql_requirements.must_include_features and "baseline_" not in sql_lower:
        failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.MISSING_PERIOD_PAIR, "baseline period", None, plan, sql))
    if "cohort_filter" in case.sql_requirements.must_include_features:
        if "datediff(hour" not in sql_lower or not re.search(r"between\s+0\s+and\s+(24|48)", sql_lower):
            failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.MISSING_COHORT_FILTER, "DATEDIFF hour BETWEEN 0 AND 24/48", None, plan, sql))
    if "default_having_minimum_sample" in case.sql_requirements.must_not_include_features and tree.find(exp.Having):
        failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.MISSING_PERIOD_PAIR, "no HAVING sample filter", "HAVING", plan, sql))
    if "status_where_breaks_denominator" in case.sql_requirements.must_not_include_features:
        where = tree.find(exp.Where)
        if where and "randevudurumu" in where.sql(dialect="tsql").lower():
            failures.append(_failure(case, EvaluationStage.SQL_SEMANTICS, FailureCode.STATUS_FILTER_BREAKS_DENOMINATOR, "conditional numerator", "status WHERE", plan, sql))
    return _stage(EvaluationStage.SQL_SEMANTICS, failures, start)


def score_result_contract(
    case: EvaluationCase,
    normalized: NormalizedResult | None,
    *,
    plan: QueryPlan | None = None,
    sql: str | None = None,
) -> StageResult:
    start = time.perf_counter()
    failures: list[FailureRecord] = []
    if normalized is None:
        if case.expected.result_contract:
            failures.append(_failure(case, EvaluationStage.RESULT_CONTRACT, FailureCode.RESULT_CONTRACT_MISMATCH, case.expected.result_contract, None, plan, sql))
        return _stage(EvaluationStage.RESULT_CONTRACT, failures, start)
    if case.expected.result_contract and normalized.schema_name != case.expected.result_contract:
        failures.append(_failure(case, EvaluationStage.RESULT_CONTRACT, FailureCode.RESULT_CONTRACT_MISMATCH, case.expected.result_contract, normalized.schema_name, plan, sql, result_shape=_shape(normalized)))
    if any("missing expected aliases" in warning for warning in normalized.warnings):
        failures.append(_failure(case, EvaluationStage.RESULT_CONTRACT, FailureCode.RESULT_ALIAS_MISSING, "aliases", normalized.warnings, plan, sql, result_shape=_shape(normalized)))
    if any("typed result validation failed" in warning for warning in normalized.warnings):
        failures.append(_failure(case, EvaluationStage.RESULT_CONTRACT, FailureCode.RESULT_NORMALIZATION_FAILURE, "valid typed result", normalized.warnings, plan, sql, result_shape=_shape(normalized)))
    for row in normalized.rows[:10]:
        for column, value in row.items():
            lowered = column.lower()
            if isinstance(value, Number) and not isinstance(value, bool):
                if any(marker in lowered for marker in ("count", "total", "appointments")) and value < 0:
                    failures.append(_failure(case, EvaluationStage.RESULT_CONTRACT, FailureCode.RESULT_NORMALIZATION_FAILURE, "non-negative count", value, plan, sql, result_shape=_shape(normalized)))
                is_level_percentage = (
                    any(marker in lowered for marker in ("rate", "percent", "percentage", "share"))
                    and "change" not in lowered
                )
                if is_level_percentage and not 0 <= float(value) <= 100:
                    failures.append(_failure(case, EvaluationStage.RESULT_CONTRACT, FailureCode.RESULT_NORMALIZATION_FAILURE, "0-100 percentage", value, plan, sql, result_shape=_shape(normalized)))
    return _stage(EvaluationStage.RESULT_CONTRACT, failures, start)


def score_final_answer(case: EvaluationCase, answer: str | None) -> StageResult:
    start = time.perf_counter()
    failures: list[FailureRecord] = []
    text = (answer or "").strip()
    lowered = text.lower()
    if case.answer_requirements.must_not_return_generic_error and any(marker in lowered for marker in GENERIC_ERROR_MARKERS):
        failures.append(_failure(case, EvaluationStage.FINAL_ANSWER, FailureCode.GENERIC_FINAL_ERROR, "specific answer", text[:200]))
    if case.answer_requirements.must_not_return_raw_row_dump and _looks_like_raw_dump(text):
        failures.append(_failure(case, EvaluationStage.FINAL_ANSWER, FailureCode.RAW_ROW_DUMP, "summary", text[:200]))
    if case.answer_requirements.must_mention_assumptions and "yorum" not in lowered and "varsay" not in lowered:
        failures.append(_failure(case, EvaluationStage.FINAL_ANSWER, FailureCode.ANSWER_DOES_NOT_ADDRESS_QUESTION, "assumption mention", text[:200]))
    if case.answer_requirements.must_summarize_findings and not text:
        failures.append(_failure(case, EvaluationStage.FINAL_ANSWER, FailureCode.ANSWER_DOES_NOT_ADDRESS_QUESTION, "summary", None))
    return _stage(EvaluationStage.FINAL_ANSWER, failures, start)


def _expected_aliases(contract: str | None, aliases: list[str]) -> list[str]:
    if not contract or not aliases:
        return []
    expected_by_contract = {
        # Full verified-status distribution; there is no 'İptal' in the data,
        # so the cohort contract carries no cancelled fields.
        "CohortResult": {
            "cohort_total_count", "completed_rate", "checked_in_rate",
            "no_show_rate", "in_progress_rate", "waiting_rate",
        },
        "PeriodComparisonResult": {"current_period_count", "baseline_period_count"},
        "VarianceResult": {"group_count", "average_appointments", "maximum_appointments"},
    }
    expected = expected_by_contract.get(contract, set())
    return sorted(expected - set(aliases))


def _has_column(tree: exp.Expression, column: str) -> bool:
    target = column.lower()
    return any(col.name.lower() == target for col in tree.find_all(exp.Column))


def _raw_detail_projection(tree: exp.Expression) -> bool:
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if not select:
        return False
    projections = list(select.expressions)
    has_aggregate = any(any(node for node in proj.find_all(exp.AggFunc)) for proj in projections)
    if not has_aggregate:
        return False
    rendered = " ".join(proj.sql(dialect="tsql") for proj in projections).lower()
    return any(column.lower() in rendered for column in RAW_DETAIL_COLUMNS)


def _looks_like_raw_dump(text: str) -> bool:
    return text.count("\n") > 80 or text.count("|") > 120 or text.count("{") > 20


def _shape(normalized: NormalizedResult) -> dict[str, Any]:
    return {
        "schema": normalized.schema_name,
        "columns": normalized.columns,
        "row_count": len(normalized.rows),
        "warnings": normalized.warnings,
    }


def _stage(stage: EvaluationStage, failures: list[FailureRecord], start: float) -> StageResult:
    return StageResult(
        stage=stage,
        passed=not failures,
        duration_ms=(time.perf_counter() - start) * 1000,
        failures=failures,
    )


def _failure(
    case: EvaluationCase,
    stage: EvaluationStage,
    code: FailureCode,
    expected: Any,
    actual: Any,
    plan: QueryPlan | None = None,
    sql: str | None = None,
    exception_type: str | None = None,
    result_shape: dict[str, Any] | None = None,
) -> FailureRecord:
    return FailureRecord(
        case_id=case.id,
        stage=stage,
        failure_code=code,
        expected=expected,
        actual=actual,
        component=_component(stage),
        generated_plan=plan.model_dump() if plan else None,
        generated_sql=sql,
        result_shape=result_shape,
        exception_type=exception_type,
    )


def _component(stage: EvaluationStage) -> str:
    return {
        EvaluationStage.ROUTING: "QueryAnalyzer",
        EvaluationStage.QUERY_PLAN: "QueryPlanner",
        EvaluationStage.SQL_GENERATION: "DeterministicSQLBuilder/SQLService",
        EvaluationStage.SQL_SEMANTICS: "sqlglot/SQLValidator",
        EvaluationStage.EXECUTION: "ExecutionService",
        EvaluationStage.RESULT_CONTRACT: "TypedResultNormalizer",
        EvaluationStage.FINAL_ANSWER: "Report/Answer deterministic checks",
    }[stage]
