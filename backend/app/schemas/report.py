from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Request
# ─────────────────────────────────────────────

class ReportRequest(BaseModel):
    """API request payload for the AI report generation endpoint."""

    question: str = Field(
        ...,
        min_length=3,
        description="Natural-language question to answer from the database.",
        json_schema_extra={
            "example": "Which doctor has the highest number of appointments?"
        },
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "question": "Which doctor has the highest number of appointments?"
            }
        }
    }


# ─────────────────────────────────────────────
# Response sub-schemas
# ─────────────────────────────────────────────

class QueryResultSchema(BaseModel):
    """Transport-layer representation of the database execution result set."""

    columns: List[str] = Field(..., description="Ordered list of result column names.")
    rows: List[Dict[str, Any]] = Field(..., description="List of result row dictionaries.")
    row_count: int = Field(..., description="Total number of rows returned by the query.")


class ReportSchema(BaseModel):
    """Transport-layer representation of the generated narrative report."""

    title: Optional[str] = Field(default=None, description="Report title extracted from the LLM output.")
    markdown: str = Field(..., description="Full markdown-formatted report narrative.")


class MetadataSchema(BaseModel):
    """Observability metadata about the LLM execution and report generation."""

    provider: str = Field(..., description="Name of the LLM provider used.")
    model: str = Field(..., description="Name of the LLM model used.")
    latency_ms: float = Field(..., description="Report generation latency in milliseconds.")
    prompt_tokens: Optional[int] = Field(default=None, description="Number of tokens in the prompt.")
    completion_tokens: Optional[int] = Field(default=None, description="Number of tokens in the completion.")


# ─────────────────────────────────────────────
# Response
# ─────────────────────────────────────────────

class IntentSchema(BaseModel):
    """Transport-layer representation of the classified user intent."""

    intent: str = Field(..., description="The classified intent type.")
    confidence: float = Field(..., description="Classification confidence score.")
    reason: Optional[str] = Field(default=None, description="Detailed explanation of classification.")
    matched_keywords: List[str] = Field(default_factory=list, description="Keywords matched.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata dictionary for routing details.")


class VisualizationSchema(BaseModel):
    """Transport-layer visualization recommendation (metadata only, no rendering)."""

    type: str = Field(..., description="Recommended visualization type (CARD, TABLE, BAR_CHART, LINE_CHART, PIE_CHART).")
    reason: str = Field(..., description="Deterministic reason behind the recommendation.")


class AnalyticsSchema(BaseModel):
    """Transport-layer representation of the deterministic analytics result."""

    analytics_type: str = Field(..., description="Primary analytics classification (trend, comparison, ranking...).")
    intents: List[str] = Field(default_factory=list, description="All detected analytical intents.")
    data_shape: str = Field(..., description="Structural classification of the result set.")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Deterministically calculated metrics.")
    insights: Dict[str, Any] = Field(default_factory=dict, description="Structured summary fields prepared for future insight generation.")
    visualization: Optional[VisualizationSchema] = Field(default=None, description="Recommended visualization metadata.")
    row_count: int = Field(default=0, description="Number of rows analyzed.")


class InsightSchema(BaseModel):
    """Transport-layer representation of the executive insight narrative."""

    title: str = Field(..., description="Short descriptive insight title.")
    summary: str = Field(..., description="Executive summary grounded in the analytics.")
    highlights: List[str] = Field(default_factory=list, description="Key observations.")
    observations: List[str] = Field(default_factory=list, description="Important findings and business interpretation.")
    considerations: List[str] = Field(default_factory=list, description="Potential considerations supported by the analytics.")
    rules: List[str] = Field(default_factory=list, description="Deterministic business rules detected before narrative generation.")
    confidence: str = Field(..., description="Deterministically computed confidence level (HIGH, MEDIUM, LOW).")
    llm_generated: bool = Field(default=False, description="Whether the narrative was produced by the LLM or deterministic templates.")


class ObservationItemSchema(BaseModel):
    """A single noteworthy, evidence-based observation."""

    rule: str = Field(..., description="Deterministic rule that produced the observation.")
    category: str = Field(..., description="Observation category (growth, trend, distribution...).")
    text: str = Field(..., description="Neutral, evidence-based observation wording.")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Metric values grounding the observation.")


class ObservationsSchema(BaseModel):
    """Transport-layer representation of the observation layer."""

    observations: List[ObservationItemSchema] = Field(default_factory=list, description="Noteworthy facts.")
    confidence: str = Field(..., description="Deterministically computed confidence (HIGH, MEDIUM, LOW).")
    llm_worded: bool = Field(default=False, description="Whether the LLM reworded the deterministic texts.")


class TimingSchema(BaseModel):
    """Transport-layer representation of per-node workflow execution timings."""

    analyze_intent_ms: Optional[float] = Field(default=None, description="Intent analysis node duration (ms).")
    analyze_results_ms: Optional[float] = Field(default=None, description="Analytics engine node duration (ms).")
    generate_insights_ms: Optional[float] = Field(default=None, description="Insight engine node duration (ms).")
    generate_observations_ms: Optional[float] = Field(default=None, description="Observation engine node duration (ms).")
    retrieve_context_ms: Optional[float] = Field(default=None, description="Schema retrieval duration (ms).")
    generate_sql_ms: Optional[float] = Field(default=None, description="SQL generation node duration (ms).")
    validate_sql_ms: Optional[float] = Field(default=None, description="SQL validation duration (ms).")
    execute_sql_ms: Optional[float] = Field(default=None, description="SQL execution duration (ms).")
    generate_report_ms: Optional[float] = Field(default=None, description="Report generation node duration (ms).")
    llm_total_ms: Optional[float] = Field(default=None, description="Aggregated LLM inference time: SQL + Report (ms).")
    total_ms: float = Field(default=0.0, description="Sum of all node execution times (ms).")


class ReportResponse(BaseModel):
    """API response payload returned by the AI report generation endpoint."""

    success: bool = Field(..., description="Indicates whether the workflow completed without errors.")
    workflow_id: Optional[str] = Field(default=None, description="Unique identifier for the workflow execution run.")
    question: str = Field(..., description="The original user question echoed back.")
    generated_sql: Optional[str] = Field(default=None, description="SQL statement generated and executed during the workflow.")
    query_result: Optional[QueryResultSchema] = Field(default=None, description="Structured database result set.")
    report: Optional[ReportSchema] = Field(default=None, description="Generated narrative report.")
    metadata: Optional[MetadataSchema] = Field(default=None, description="LLM execution observability metadata.")
    timing: Optional[TimingSchema] = Field(default=None, description="Per-node workflow execution timing breakdown.")
    intent: Optional[IntentSchema] = Field(default=None, description="Classified intent payload.")
    analytics: Optional[AnalyticsSchema] = Field(
        default=None, description="Deterministic analytics computed from the query result."
    )
    insights: Optional[InsightSchema] = Field(
        default=None, description="Executive insight narrative grounded in the analytics."
    )
    observations: Optional[ObservationsSchema] = Field(
        default=None, description="Layer 4: noteworthy evidence-based observations."
    )
    visualization: Optional[VisualizationSchema] = Field(
        default=None,
        description="Layer 5: recommended visualization metadata (mirrors analytics.visualization).",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "workflow_id": "wf-abc123",
                "question": "Which doctor has the highest number of appointments?",
                "generated_sql": "SELECT d.ad_soyad, COUNT(r.id) AS randevu_sayisi FROM doktorlar d JOIN randevular r ON d.id = r.doktor_id GROUP BY d.ad_soyad ORDER BY randevu_sayisi DESC LIMIT 1;",
                "query_result": {
                    "columns": ["ad_soyad", "randevu_sayisi"],
                    "rows": [{"ad_soyad": "Tekbay Aksu", "randevu_sayisi": 155}],
                    "row_count": 1,
                },
                "report": {
                    "title": "Doctor Appointment Report",
                    "markdown": "# Doctor Appointment Report\n\n## Key Findings\n...",
                },
                "metadata": {
                    "provider": "ollama",
                    "model": "qwen3:8b",
                    "latency_ms": 210.0,
                    "prompt_tokens": 350,
                    "completion_tokens": 180,
                },
            }
        }
    }


__all__ = [
    "ReportRequest",
    "ReportResponse",
    "QueryResultSchema",
    "ReportSchema",
    "MetadataSchema",
    "TimingSchema",
    "IntentSchema",
    "AnalyticsSchema",
    "VisualizationSchema",
    "InsightSchema",
    "ObservationsSchema",
    "ObservationItemSchema",
]
