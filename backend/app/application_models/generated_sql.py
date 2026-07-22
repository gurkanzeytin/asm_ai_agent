from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class GeneratedSQL(BaseModel):
    """Shared application DTO model representing safety validated generated SQL metadata."""

    model_config = ConfigDict(frozen=True)

    sql: str = Field(..., description="The raw generated and parsed SQL query.")
    normalized_sql: Optional[str] = Field(default=None, description="The AST-normalized query format.")
    validation_result: Optional[Any] = Field(default=None, description="The safety validator result output.")
    provider: str = Field(..., description="The LLM provider name identifier.")
    model: str = Field(..., description="The target LLM model identifier.")
    latency_ms: float = Field(..., description="The generation execution time in milliseconds.")
    prompt_tokens: Optional[int] = Field(default=None, description="The prompt token count.")
    completion_tokens: Optional[int] = Field(default=None, description="The completion token count.")
    rendered_prompt: Optional[str] = Field(
        default=None,
        description="The fully rendered prompt submitted to the LLM. Populated for observability/tracing; not exposed in API responses.",
    )
    sql_source: Optional[str] = Field(
        default=None,
        description="Internal generation source: deterministic, llm, or repaired_llm.",
    )
    result_schema: Optional[str] = Field(
        default=None,
        description="Internal typed result contract selected for deterministic SQL.",
    )
    expected_aliases: list[str] = Field(
        default_factory=list,
        description="Internal fixed result aliases expected from deterministic SQL.",
    )
    metric_aliases: dict[str, str] = Field(
        default_factory=dict,
        description="Metric catalog id -> SELECT alias, for deterministic multi-metric SQL.",
    )
    repair_attempted: bool = Field(
        default=False,
        description="Whether a bounded deterministic metric-coverage repair was attempted.",
    )
    repair_reason: Optional[str] = Field(
        default=None,
        description="Why a repair/fallback was needed, e.g. a metric-alias coverage gap.",
    )
    missing_metrics_before: list[str] = Field(
        default_factory=list,
        description="Metric ids missing from the deterministic SQL before the LLM fallback ran.",
    )
    missing_metrics_after: list[str] = Field(
        default_factory=list,
        description="Metric ids still missing from the final SQL after generation completed.",
    )
