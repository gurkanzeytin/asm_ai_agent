from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FailureCode(StrEnum):
    ROUTING_OUT_OF_SCOPE_FALSE_POSITIVE = "ROUTING_OUT_OF_SCOPE_FALSE_POSITIVE"
    ROUTING_IN_SCOPE_FALSE_POSITIVE = "ROUTING_IN_SCOPE_FALSE_POSITIVE"
    CLARIFICATION_MISSED = "CLARIFICATION_MISSED"
    CLARIFICATION_UNNECESSARY = "CLARIFICATION_UNNECESSARY"
    WRONG_ANALYSIS_TYPE = "WRONG_ANALYSIS_TYPE"
    WRONG_METRIC = "WRONG_METRIC"
    WRONG_DIMENSION = "WRONG_DIMENSION"
    WRONG_DATE_CONTEXT = "WRONG_DATE_CONTEXT"
    WRONG_BASELINE = "WRONG_BASELINE"
    WRONG_COHORT = "WRONG_COHORT"
    PLAN_NOT_ANSWERABLE = "PLAN_NOT_ANSWERABLE"
    DETERMINISTIC_BUILDER_NOT_SELECTED = "DETERMINISTIC_BUILDER_NOT_SELECTED"
    INVALID_SQL = "INVALID_SQL"
    UNKNOWN_COLUMN = "UNKNOWN_COLUMN"
    WRONG_VIEW = "WRONG_VIEW"
    RAW_DETAIL_INSTEAD_OF_AGGREGATE = "RAW_DETAIL_INSTEAD_OF_AGGREGATE"
    MISSING_GROUP_BY = "MISSING_GROUP_BY"
    WRONG_RATIO_DENOMINATOR = "WRONG_RATIO_DENOMINATOR"
    STATUS_FILTER_BREAKS_DENOMINATOR = "STATUS_FILTER_BREAKS_DENOMINATOR"
    MISSING_PERIOD_PAIR = "MISSING_PERIOD_PAIR"
    WRONG_PERIOD_RANGE = "WRONG_PERIOD_RANGE"
    MISSING_COHORT_FILTER = "MISSING_COHORT_FILTER"
    RESULT_CONTRACT_MISMATCH = "RESULT_CONTRACT_MISMATCH"
    RESULT_ALIAS_MISSING = "RESULT_ALIAS_MISSING"
    RESULT_NORMALIZATION_FAILURE = "RESULT_NORMALIZATION_FAILURE"
    EMPTY_RESULT_WITHOUT_RETRY = "EMPTY_RESULT_WITHOUT_RETRY"
    RETRY_NOT_EXECUTED = "RETRY_NOT_EXECUTED"
    RETRY_STILL_GENERIC = "RETRY_STILL_GENERIC"
    RESULT_REASONING_FAILURE = "RESULT_REASONING_FAILURE"
    GENERIC_FINAL_ERROR = "GENERIC_FINAL_ERROR"
    WRONG_SCOPE_MESSAGE = "WRONG_SCOPE_MESSAGE"
    RAW_ROW_DUMP = "RAW_ROW_DUMP"
    ANSWER_DOES_NOT_ADDRESS_QUESTION = "ANSWER_DOES_NOT_ADDRESS_QUESTION"
    TIMEOUT = "TIMEOUT"
    LLM_FALLBACK_INSTABILITY = "LLM_FALLBACK_INSTABILITY"


class EvaluationStage(StrEnum):
    ROUTING = "routing"
    QUERY_PLAN = "query_plan"
    SQL_GENERATION = "sql_generation"
    SQL_SEMANTICS = "sql_semantics"
    EXECUTION = "execution"
    RESULT_CONTRACT = "result_contract"
    FINAL_ANSWER = "final_answer"


class EvaluationMode(StrEnum):
    PLANNER_ONLY = "planner-only"
    SQL_GENERATION = "sql-generation"
    MOCKED_EXECUTION = "mocked-execution"
    LIVE_DB = "live-db"
    FULL_ENDPOINT = "full-endpoint"


class ExpectedEvaluation(BaseModel):
    in_scope: bool = True
    analysis_type: str | None = None
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    sql_source: str | None = None
    result_contract: str | None = None
    raw_detail_allowed: bool = False
    clarification_required: bool = False
    answerable: bool = True
    current_period: str | None = None
    baseline_period: str | None = None
    cohort: str | None = None
    minimum_sample_size: int | None = None


class SQLRequirements(BaseModel):
    must_use_columns: list[str] = Field(default_factory=list)
    must_include_features: list[str] = Field(default_factory=list)
    must_not_include_features: list[str] = Field(default_factory=list)
    must_not_use_columns: list[str] = Field(default_factory=list)


class AnswerRequirements(BaseModel):
    must_mention_assumptions: bool = False
    must_summarize_findings: bool = True
    must_not_return_generic_error: bool = True
    must_not_return_raw_row_dump: bool = True


class EvaluationCase(BaseModel):
    id: str
    question: str
    category: str
    difficulty: str = "medium"
    blind: bool = True
    suite: str = "blind"
    requires_live_db: bool = False
    expected: ExpectedEvaluation
    sql_requirements: SQLRequirements = Field(default_factory=SQLRequirements)
    answer_requirements: AnswerRequirements = Field(default_factory=AnswerRequirements)


class EvaluationDataset(BaseModel):
    version: int = 1
    view: str = "dbo.vw_RandevuRaporu"
    cases: list[EvaluationCase]


class FailureRecord(BaseModel):
    case_id: str
    stage: EvaluationStage
    failure_code: FailureCode
    expected: Any = None
    actual: Any = None
    component: str = ""
    generated_plan: dict[str, Any] | None = None
    generated_sql: str | None = None
    result_shape: dict[str, Any] | None = None
    exception_type: str | None = None
    duration_ms: float = 0.0


class StageResult(BaseModel):
    stage: EvaluationStage
    passed: bool = True
    skipped: bool = False
    duration_ms: float = 0.0
    failures: list[FailureRecord] = Field(default_factory=list)


class CaseResult(BaseModel):
    case_id: str
    question: str
    category: str
    mode: EvaluationMode
    passed: bool = True
    skipped: bool = False
    skip_reason: str | None = None
    sql_source: str | None = None
    result_contract: str | None = None
    row_count: int | None = None
    total_ms: float = 0.0
    stage_results: list[StageResult] = Field(default_factory=list)
    failures: list[FailureRecord] = Field(default_factory=list)
    generated_sql: str | None = None
    plan_summary: dict[str, Any] | None = None

    # Optional LLM provider metadata (AI-INTELLIGENCE-010 extension for NVIDIA
    # provider integration). All fields are optional/defaulted so older stored
    # evaluation result JSON files without these keys still load unchanged.
    llm_provider: str | None = None
    llm_model: str | None = None
    thinking_mode: bool | None = None
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None
    remote_data_policy: str | None = None
    # Hybrid provider fallback is not implemented yet; always False for now.
    fallback_used: bool = False


class EvaluationSummary(BaseModel):
    total_cases: int
    passed: int
    failed: int
    skipped: int
    layer_accuracy: dict[str, float] = Field(default_factory=dict)
    failure_counts: dict[str, int] = Field(default_factory=dict)
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0
    deterministic_sql_avg_ms: float = 0.0
    llm_sql_avg_ms: float = 0.0
    live_execution_avg_ms: float = 0.0
    timeout_rate: float = 0.0


class EvaluationRun(BaseModel):
    run_id: str
    generated_at: str
    suite: str
    mode: EvaluationMode
    environment: dict[str, Any] = Field(default_factory=dict)
    summary: EvaluationSummary
    results: list[CaseResult]
    previous_comparison: dict[str, Any] = Field(default_factory=dict)
