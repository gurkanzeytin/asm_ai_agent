"""Outcome classification and metric aggregation for benchmark runs.

Everything here is deterministic and side-effect free so it can be unit tested
without an LLM.
"""

import statistics
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from tools.benchmark.config import (
    SCORE_SPEED_WEIGHT,
    SCORE_SUCCESS_WEIGHT,
    SPEED_FAST_MS,
    SPEED_SLOW_MS,
)


class Outcome(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class Reason(StrEnum):
    OK = "ok"
    SQL_GENERATION_FAILED = "sql_generation_failed"
    INVALID_SQL = "invalid_sql"
    WRONG_ENTITY = "wrong_entity"
    WRONG_JOIN = "wrong_join"
    TIMEOUT = "timeout"
    NO_RESULTS = "no_results"
    NO_ANALYTICS = "no_analytics"
    PIPELINE_FAILURE = "pipeline_failure"


# Categories where "handled without crashing" is the success criterion.
GRACEFUL_CATEGORIES = {"ambiguous", "graceful_failure"}
# Categories whose success additionally requires an analytics result.
ANALYTICAL_CATEGORIES = {"trend", "analytics", "comparison"}

# Question noun (folded, prefix-matched) -> acceptable table name fragments.
ENTITY_TABLE_HINTS: dict[str, tuple[str, ...]] = {
    "randevu": ("randevular",),
    "doktor": ("doktorlar",),
    "hasta": ("hastalar", "randevular"),
    "bolum": ("bolumler", "randevular", "doktorlar"),
    "recete": ("receteler",),
    "oda": ("odalar",),
    "sigorta": ("sigorta_sirketleri",),
    "fatura": ("faturalar",),
}

_FOLD = str.maketrans({"ı": "i", "ğ": "g", "ş": "s", "ç": "c", "ö": "o", "ü": "u"})


def _fold(text: str) -> str:
    return text.replace("İ", "i").lower().translate(_FOLD)


@dataclass
class QuestionRun:
    """Raw observation of one question executed against one model."""

    model: str
    question_id: int
    category: str
    question: str
    repeat_index: int = 0
    generated_sql: str | None = None
    execution_success: bool = False
    rows_returned: int = 0
    analytics_generated: bool = False
    insight_generated: bool = False
    report_generated: bool = False
    errors: list[str] = field(default_factory=list)
    exception: str | None = None
    total_ms: float = 0.0
    sql_generation_ms: float = 0.0
    analytics_ms: float = 0.0
    insight_ms: float = 0.0
    report_ms: float = 0.0
    llm_calls: int = 0
    llm_timeouts: int = 0
    retry_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reasons: list[str] = field(default_factory=list)
    outcome: str = Outcome.FAILED.value
    reason: str = Reason.PIPELINE_FAILURE.value

    def to_dict(self) -> dict:
        return asdict(self)


def classify(run: QuestionRun) -> tuple[Outcome, Reason]:
    """Deterministically classifies a run as SUCCESS / PARTIAL / FAILED."""
    if run.category in GRACEFUL_CATEGORIES:
        # These questions succeed when the pipeline answers or degrades without
        # crashing; a captured error message is a graceful outcome by design.
        if run.exception:
            return Outcome.FAILED, Reason.PIPELINE_FAILURE
        return Outcome.SUCCESS, Reason.OK

    if run.exception:
        return Outcome.FAILED, Reason.PIPELINE_FAILURE
    if run.llm_timeouts > 0 and not run.report_generated and not run.execution_success:
        return Outcome.FAILED, Reason.TIMEOUT
    if not run.generated_sql:
        return Outcome.FAILED, Reason.SQL_GENERATION_FAILED
    if not run.execution_success:
        return Outcome.FAILED, Reason.INVALID_SQL

    wrong_entity = _wrong_entity(run.question, run.generated_sql)
    if wrong_entity:
        return Outcome.PARTIAL, Reason.WRONG_ENTITY
    if run.rows_returned == 0:
        return Outcome.PARTIAL, Reason.NO_RESULTS
    if run.category in ANALYTICAL_CATEGORIES and not run.analytics_generated:
        return Outcome.PARTIAL, Reason.NO_ANALYTICS
    return Outcome.SUCCESS, Reason.OK


def _wrong_entity(question: str, sql: str) -> bool:
    """True when the question names a domain entity whose tables never appear in the SQL."""
    folded_question = _fold(question)
    folded_sql = _fold(sql)
    for noun, tables in ENTITY_TABLE_HINTS.items():
        if noun in folded_question:
            if not any(table in folded_sql for table in tables):
                return True
    return False


@dataclass
class ModelSummary:
    model: str
    total_questions: int
    success: int
    partial: int
    failed: int
    success_rate: float
    partial_rate: float
    avg_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    avg_sql_generation_ms: float
    avg_analytics_ms: float
    avg_insight_ms: float
    avg_report_ms: float
    avg_total_llm_ms: float
    retry_rate: float
    timeout_rate: float
    avg_prompt_tokens: float
    avg_completion_tokens: float
    avg_total_tokens: float
    overall_score: float
    category_success: dict[str, float] = field(default_factory=dict)
    failure_reasons: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, round(pct / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def summarize_model(model: str, runs: list[QuestionRun]) -> ModelSummary:
    """Aggregates all runs of one model into a ModelSummary."""
    total = len(runs)
    if total == 0:
        raise ValueError(f"No runs recorded for model {model}.")

    latencies = [run.total_ms for run in runs]
    success = sum(1 for run in runs if run.outcome == Outcome.SUCCESS)
    partial = sum(1 for run in runs if run.outcome == Outcome.PARTIAL)
    failed = total - success - partial
    success_rate = success / total
    avg_latency = statistics.fmean(latencies)

    speed_score = _speed_score(avg_latency)
    overall_score = round(
        SCORE_SUCCESS_WEIGHT * success_rate + SCORE_SPEED_WEIGHT * speed_score, 4
    )

    category_success: dict[str, float] = {}
    for category in {run.category for run in runs}:
        cat_runs = [run for run in runs if run.category == category]
        cat_success = sum(1 for run in cat_runs if run.outcome == Outcome.SUCCESS)
        category_success[category] = round(cat_success / len(cat_runs) * 100, 1)

    failure_reasons: dict[str, int] = {}
    for run in runs:
        if run.outcome != Outcome.SUCCESS and run.reason != Reason.OK:
            failure_reasons[run.reason] = failure_reasons.get(run.reason, 0) + 1

    return ModelSummary(
        model=model,
        total_questions=total,
        success=success,
        partial=partial,
        failed=failed,
        success_rate=round(success_rate * 100, 1),
        partial_rate=round(partial / total * 100, 1),
        avg_latency_ms=round(avg_latency, 1),
        median_latency_ms=round(statistics.median(latencies), 1),
        p95_latency_ms=round(percentile(latencies, 95), 1),
        avg_sql_generation_ms=round(statistics.fmean([r.sql_generation_ms for r in runs]), 1),
        avg_analytics_ms=round(statistics.fmean([r.analytics_ms for r in runs]), 2),
        avg_insight_ms=round(statistics.fmean([r.insight_ms for r in runs]), 1),
        avg_report_ms=round(statistics.fmean([r.report_ms for r in runs]), 1),
        avg_total_llm_ms=round(
            statistics.fmean(
                [r.sql_generation_ms + r.insight_ms + r.report_ms for r in runs]
            ),
            1,
        ),
        retry_rate=round(sum(1 for r in runs if r.retry_count > 0) / total * 100, 1),
        timeout_rate=round(sum(1 for r in runs if r.llm_timeouts > 0) / total * 100, 1),
        avg_prompt_tokens=round(statistics.fmean([r.prompt_tokens for r in runs]), 1),
        avg_completion_tokens=round(
            statistics.fmean([r.completion_tokens for r in runs]), 1
        ),
        avg_total_tokens=round(
            statistics.fmean([r.prompt_tokens + r.completion_tokens for r in runs]), 1
        ),
        overall_score=overall_score,
        category_success=category_success,
        failure_reasons=failure_reasons,
    )


def _speed_score(avg_latency_ms: float) -> float:
    """Maps average latency onto [0, 1]: fast -> 1, slow -> 0, linear between."""
    if avg_latency_ms <= SPEED_FAST_MS:
        return 1.0
    if avg_latency_ms >= SPEED_SLOW_MS:
        return 0.0
    span = SPEED_SLOW_MS - SPEED_FAST_MS
    return round(1.0 - (avg_latency_ms - SPEED_FAST_MS) / span, 4)


def rank_models(summaries: list[ModelSummary]) -> list[ModelSummary]:
    """Sorts summaries by overall score (desc), tie-broken by success rate then speed."""
    return sorted(
        summaries,
        key=lambda s: (-s.overall_score, -s.success_rate, s.avg_latency_ms),
    )
