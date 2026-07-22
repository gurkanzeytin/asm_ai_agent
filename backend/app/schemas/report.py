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
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional conversational session key for follow-up resolution. Reuse the same "
            "value across turns of one conversation to enable follow-up inheritance. Omitted "
            "clients each get a fresh, isolated ephemeral session — never a shared 'default' "
            "session — so independent requests can never contaminate each other's context. "
            "The resolved session_id is always echoed back in the response."
        ),
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

class ColumnMetadataSchema(BaseModel):
    """Presentation metadata for a single QueryResult column (AI-INTELLIGENCE-013).

    Additive only: `key` always matches an entry in `QueryResultSchema.columns`
    and every row's raw key — data access, sorting, filtering, and exports
    must keep using `key`, never `label`.
    """

    key: str = Field(..., description="Raw canonical column key (matches columns[]/row keys).")
    label: str = Field(..., description="Türkçe display label for this column.")
    format: str = Field(
        ...,
        description="Presentation format hint: text, integer, decimal, percentage, duration, "
        "date, or datetime. Never mutates the raw value.",
    )
    unit: Optional[str] = Field(
        default=None, description="Display unit for the formatted value (e.g. '%', 'dakika')."
    )


class QueryResultSchema(BaseModel):
    """Transport-layer representation of the database execution result set."""

    columns: List[str] = Field(..., description="Ordered list of result column names.")
    rows: List[Dict[str, Any]] = Field(..., description="List of result row dictionaries.")
    row_count: int = Field(
        ...,
        description="Backward-compatible alias of returned_row_count at the API boundary.",
    )
    source_record_count: Optional[int] = Field(
        default=None, description="Underlying source records only when genuinely known."
    )
    result_group_count: Optional[int] = Field(
        default=None, description="Complete analytical group count when genuinely known."
    )
    returned_row_count: int = Field(
        default=0, description="Rows serialized in this API response (maximum 500)."
    )
    displayed_row_count: int = Field(
        default=0, description="Rows intended for one visible UI page (maximum 100)."
    )
    result_truncated: bool = Field(
        default=False, description="Whether rows were omitted at any safety boundary."
    )
    applied_limit: int = Field(default=500, description="API serialization row cap.")
    has_more: bool = Field(
        default=False, description="Whether additional rows are known to exist."
    )
    total_count: Optional[int] = Field(
        default=None, description="Exact total only when already known; never estimated."
    )
    column_metadata: List[ColumnMetadataSchema] = Field(
        default_factory=list,
        description="Presentation metadata (Türkçe label/format/unit) per column, in `columns` "
        "order. Additive only — `columns` and `rows` keep their raw canonical keys unchanged "
        "for data access, sorting, filtering, and exports.",
    )


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
    technical_row_count: int = Field(
        default=0, description="Physical SQL rows returned; technical metadata only."
    )
    business_record_count: Optional[int] = Field(
        default=None, description="Business record count only when the result represents raw records."
    )
    result_shape: str = Field(default="empty", description="Plan-aware semantic result shape.")
    aggregate_result: bool = False
    displayable_kpis: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Authoritative business KPI cards safe for user-facing presentation.",
    )
    metric_summaries: Dict[str, Any] = Field(
        default_factory=dict,
        description="Per-metric aggregate summaries (metric_id -> total/average/min/max/top/"
        "bottom dimension/label), present only for multi-metric requests.",
    )
    comparison_category_count: Optional[int] = Field(
        default=None, description="CATEGORICAL results only: number of distinct groups compared."
    )
    comparison_sufficient: Optional[bool] = Field(
        default=None,
        description="CATEGORICAL results only: whether enough categories existed for a "
        "meaningful comparison.",
    )
    comparison_limitation_reason: Optional[str] = Field(
        default=None, description="Deterministic explanation when comparison_sufficient is false."
    )


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
    llm_invoked: bool = Field(
        default=False,
        description="Alias of llm_generated for observability consistency: whether an LLM "
        "call was actually made for this insight (false for the deterministic/template path).",
    )
    provider: Optional[str] = Field(
        default=None, description="LLM provider used, or 'deterministic' when templated."
    )
    model: Optional[str] = Field(
        default=None, description="LLM model used, or 'templates' when templated."
    )
    llm_inference_ms: Optional[float] = Field(
        default=None, description="Real LLM call latency for this insight (ms), None if deterministic."
    )
    prompt_tokens: Optional[int] = Field(default=None, description="Prompt tokens, when returned by the provider.")
    completion_tokens: Optional[int] = Field(default=None, description="Completion tokens, when returned by the provider.")
    finish_reason: Optional[str] = Field(default=None, description="Provider finish reason, when returned.")
    routing_mode: Optional[str] = Field(
        default=None,
        description="Insight generation mode selected by the router: deterministic, local_llm, "
        "or remote_llm. None when routing was not active (legacy single-provider path).",
    )
    routing_reason: Optional[str] = Field(
        default=None, description="Deterministic explanation for the routing decision."
    )
    fallback_used: bool = Field(
        default=False, description="Whether the primary selected provider failed and a fallback was used."
    )
    fallback_reason: Optional[str] = Field(default=None, description="Reason the fallback was triggered, if any.")
    remote_data_policy: Optional[str] = Field(
        default=None,
        description="Remote data policy verdict for this insight: not_applicable, allowed, or rejected.",
    )


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
    insight_llm_ms: Optional[float] = Field(
        default=None, description="Real LLM inference time inside the Insight Engine (ms), when it called an LLM."
    )
    observation_llm_ms: Optional[float] = Field(
        default=None, description="Real LLM inference time inside the Observation Engine (ms), when it called an LLM."
    )
    llm_total_ms: Optional[float] = Field(
        default=None,
        description="Aggregated real LLM inference time: SQL + Report + Insight + Observation (ms).",
    )
    total_ms: float = Field(default=0.0, description="Sum of all node execution times (ms).")


class ReportResponse(BaseModel):
    """API response payload returned by the AI report generation endpoint."""

    success: bool = Field(..., description="Indicates whether the workflow completed without errors.")
    workflow_id: Optional[str] = Field(default=None, description="Unique identifier for the workflow execution run.")
    question: str = Field(..., description="The original user question echoed back.")
    raw_question: Optional[str] = None
    resolved_question: Optional[str] = None
    answerability_input_source: str = "raw_question"
    answerability_signals: List[str] = Field(default_factory=list)
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
    outcome: Optional[str] = Field(
        default=None,
        description=(
            "Controlled outcome of the run (AG-022): EXECUTE_SQL, ASK_CLARIFICATION, "
            "RETURN_HELP, OUT_OF_SCOPE, REWRITE_AND_RETRY, NO_RESULT_GUIDANCE, SAFE_ERROR."
        ),
    )

    # Conversational context / chat-memory diagnostics (optional, backward compatible —
    # existing clients that ignore these fields are unaffected).
    session_id: Optional[str] = Field(
        default=None,
        description="Session key actually used for this run, resolved server-side "
        "(always present, even when the request omitted session_id).",
    )
    follow_up_detected: bool = Field(
        default=False,
        description="Whether a deterministic follow-up signal fired for this question "
        "(pronoun/reference, elliptical short-form, date-only or negation continuation).",
    )
    follow_up_confidence: float = Field(
        default=1.0, description="Deterministic confidence of the follow-up resolution."
    )
    follow_up_signals: List[str] = Field(
        default_factory=list, description="Names of the follow-up signals that fired."
    )
    context_applied: bool = Field(
        default=False, description="Whether session context enrichment was applied."
    )
    inherited_fields: List[str] = Field(
        default_factory=list, description="Field names inherited from session context."
    )
    overridden_fields: List[str] = Field(
        default_factory=list,
        description="Field names the current turn stated explicitly, replacing memory "
        "(explicit-value precedence made observable).",
    )
    memory_updated: bool = Field(
        default=False,
        description="Whether session context was written after this run — only true for "
        "a successful, data-bearing outcome (see write policy).",
    )
    memory_turn_count: Optional[int] = Field(
        default=None, description="Retained turn count for the session after this run."
    )
    memory_expired: bool = Field(
        default=False,
        description="Whether the session had no live context at the START of this turn "
        "(i.e. this turn began a fresh conversation window).",
    )
    memory_reset: bool = Field(
        default=False,
        description="Always false on this endpoint; reserved for parity with the "
        "DELETE /api/v1/context/{session_id} reset endpoint's response.",
    )

    # Typed analytical follow-up signals (dimensions/metrics/filters/ranking/
    # limit/time_grain/comparison_targets).
    explicit_context_fields: List[str] = Field(
        default_factory=list,
        description="Analytical field names the current turn stated explicitly.",
    )
    inherited_context_fields: List[str] = Field(
        default_factory=list, description="Field names inherited from session context."
    )
    overridden_context_fields: List[str] = Field(
        default_factory=list,
        description="Field names the current turn stated explicitly, replacing memory.",
    )
    removed_context_fields: List[str] = Field(
        default_factory=list,
        description="Field names that held a value in context but were cleared/replaced "
        "this turn.",
    )
    resolved_metrics: List[str] = Field(
        default_factory=list, description="This turn's resolved metric catalog ids."
    )
    resolved_dimensions: List[str] = Field(
        default_factory=list, description="This turn's resolved grouping dimensions."
    )
    resolved_filters: Dict[str, List[str]] = Field(
        default_factory=dict, description="This turn's resolved filter values by family."
    )
    resolved_time_grain: Optional[str] = Field(
        default=None, description="This turn's resolved time grain: day|week|month|quarter|year."
    )
    resolved_ranking: Optional[str] = Field(
        default=None, description="This turn's resolved ranking direction: top|bottom."
    )
    resolved_limit: Optional[int] = Field(
        default=None, description="This turn's resolved explicit row/group limit."
    )
    pending_clarification_field: Optional[str] = Field(
        default=None,
        description="Name of a field still awaiting clarification after this turn, "
        "or None when nothing is pending.",
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
    "ColumnMetadataSchema",
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
