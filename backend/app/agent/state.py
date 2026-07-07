from typing import List, Optional
from pydantic import BaseModel, Field

from app.application_models.generated_sql import GeneratedSQL
from app.application_models.workflow_models import QueryResult
from app.database_intelligence.models import DatabaseContext


class AgentState(BaseModel):
    """Strongly typed Pydantic state passed across workflow nodes."""

    question: str = Field(..., description="The user query input question.")
    database_context: Optional[DatabaseContext] = Field(
        default=None, description="Discovered database tables/views context."
    )
    sql_prompt: Optional[str] = Field(
        default=None, description="The final rendered SQL prompt template."
    )
    generated_sql: Optional[GeneratedSQL] = Field(
        default=None, description="Generated SQL syntax with safety validation metrics."
    )
    query_result: Optional[QueryResult] = Field(
        default=None, description="Structured SQL query execution result payload."
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
