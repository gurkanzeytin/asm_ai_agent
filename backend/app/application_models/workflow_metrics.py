from typing import Optional

from pydantic import BaseModel, Field


class WorkflowMetrics(BaseModel):
    """Typed performance metrics DTO for a completed agent workflow run.

    All node fields are Optional — nodes that did not execute remain None.
    llm_total_ms aggregates SQL + Report LLM inference time for quick profiling
    without summing individual node timings manually.
    """

    retrieve_context_ms: Optional[float] = Field(
        default=None, description="Time spent retrieving database schema context (ms)."
    )
    generate_sql_ms: Optional[float] = Field(
        default=None, description="Time spent in the SQL generation node including LLM call (ms)."
    )
    validate_sql_ms: Optional[float] = Field(
        default=None, description="Time spent validating the generated SQL (ms)."
    )
    execute_sql_ms: Optional[float] = Field(
        default=None, description="Time spent executing the SQL query against the database (ms)."
    )
    generate_report_ms: Optional[float] = Field(
        default=None, description="Time spent in the report generation node including LLM call (ms)."
    )
    analyze_intent_ms: Optional[float] = Field(
        default=None, description="Time spent in the intent classification node (ms)."
    )
    llm_total_ms: Optional[float] = Field(
        default=None,
        description="Aggregated LLM inference time: SQL generation latency + report generation latency (ms).",
    )
    total_ms: float = Field(
        default=0.0, description="Sum of all non-None node execution times (ms)."
    )
