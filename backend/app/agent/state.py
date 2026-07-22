from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from app.application_models.generated_report import GeneratedReport
from app.application_models.generated_sql import GeneratedSQL
from app.analytics.models import AnalyticsResult
from app.analytics.result_validation import ResultShapeVerdict
from app.application_models.intent import IntentResult
from app.insights.models import InsightResult
from app.intelligence.models import ObservationResult
from app.application_models.query_analysis import AmbiguityResult
from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import DatabaseContext
from app.planning.models import QueryPlan
from app.semantics.models import SemanticFrame


class AgentState(BaseModel):
    """Strongly typed Pydantic state passed across workflow nodes."""

    question: str = Field(..., description="The user query input question.")
    database_context: Optional[DatabaseContext] = Field(
        default=None, description="Discovered database tables/views context."
    )
    sql_prompt: Optional[str] = Field(
        default=None, description="The final rendered SQL prompt template (stored for observability/tracing)."
    )
    generated_sql: Optional[GeneratedSQL] = Field(
        default=None, description="Generated SQL syntax with safety validation metrics."
    )
    query_result: Optional[QueryResult] = Field(
        default=None, description="Structured SQL query execution result payload."
    )
    result_shape_verdict: Optional[ResultShapeVerdict] = Field(
        default=None,
        description="Post-execution verdict comparing result columns against the "
        "deterministic SQL's expected alias contract; gates analytics/Nemotron/report.",
    )
    analytics_blocked_reason: Optional[str] = Field(
        default=None,
        description="Set when an invalid result shape blocks analytics/insight generation "
        "for this turn; downstream nodes must produce a safe clarification instead.",
    )
    analytics: Optional[AnalyticsResult] = Field(
        default=None,
        description="Deterministic analytics computed from the executed query result.",
    )
    insights: Optional[InsightResult] = Field(
        default=None,
        description="Executive-level insight narrative grounded in the analytics result.",
    )
    observations: Optional[ObservationResult] = Field(
        default=None,
        description="Noteworthy evidence-based observations derived from analytics metadata.",
    )
    generated_report: Optional[GeneratedReport] = Field(
        default=None, description="The narrative report summary details."
    )
    errors: List[str] = Field(
        default_factory=list, description="Accumulated diagnostic or safety validation errors."
    )

    # Workflow tracing metadata
    workflow_id: Optional[str] = Field(default=None, description="Observability identifier tracking the graph execution run.")
    started_at: Optional[str] = Field(default=None, description="ISO timestamp indicating when workflow run commenced.")
    current_node: Optional[str] = Field(default=None, description="The name of the currently executing workflow node.")
    completed_nodes: List[str] = Field(default_factory=list, description="Ordered checklist tracking successful node execution history.")
    duration_ms: float = Field(default=0.0, description="Cumulative workflow processing execution time in milliseconds.")

    # Per-node timing accumulator (mapped to WorkflowMetrics at the service boundary)
    node_timings: Dict[str, float] = Field(
        default_factory=dict,
        description="Per-node execution duration in milliseconds. Keys match node names.",
    )
    intent: Optional[IntentResult] = Field(
        default=None,
        description="The analyzed user intent result details.",
    )
    ambiguity: Optional[AmbiguityResult] = Field(
        default=None,
        description="Ambiguous ranking phrase detected in the question, requiring clarification.",
    )

    query_plan: Optional[QueryPlan] = Field(
        default=None,
        description="Deterministic query plan built between NLU and SQL generation (AG-022).",
    )
    semantic_frame: Optional[SemanticFrame] = Field(
        default=None,
        description="Structured semantic interpretation of the question (REASONING-001).",
    )

    # AG-022 — controlled outcome tracking and execution retry loop
    outcome: Optional[str] = Field(
        default=None,
        description="Controlled AgentOutcome value describing how the run resolved.",
    )
    answerable: Optional[bool] = Field(
        default=None,
        description="Answerability guard verdict: whether the question maps onto the schema domain.",
    )
    sql_retry_count: int = Field(
        default=0,
        description="Number of execution-failure SQL rewrite retries already used.",
    )
    last_execution_error: Optional[str] = Field(
        default=None,
        description="Database error from the last failed execution, fed back to SQL regeneration.",
    )

