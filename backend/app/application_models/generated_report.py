from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ReportPromptContext(BaseModel):
    """Dedicated model for prompt rendering, preventing prompt templates from depending on internal DTO structures."""

    model_config = ConfigDict(frozen=True)

    question: str
    columns: List[str]
    rows: List[Dict[str, Any]]
    original_row_count: int
    truncated_row_count: Optional[int] = None


class GeneratedReport(BaseModel):
    """Shared application DTO model representing summarized report narrative outputs."""

    model_config = ConfigDict(frozen=True)

    title: Optional[str] = Field(default=None, description="The extracted report title header.")
    summary: Optional[str] = Field(default=None, description="The extracted executive summary.")
    markdown: str = Field(..., description="The narrative content in markdown formatting.")
    insights: Optional[List[str]] = Field(default=None, description="List of narrative key insights.")
    recommendations: Optional[List[str]] = Field(default=None, description="List of narrative actionable recommendations.")
    tables: Optional[List[Any]] = Field(default=None, description="Structured parsed report tables.")
    charts: Optional[List[Any]] = Field(default=None, description="Structured parsed report charts.")
    provider: str = Field(default="unknown", description="The LLM provider name identifier.")
    model: str = Field(default="unknown", description="The target LLM model identifier.")
    latency_ms: float = Field(default=0.0, description="The report generation execution time in milliseconds.")
    prompt_tokens: Optional[int] = Field(default=None, description="The prompt token count.")
    completion_tokens: Optional[int] = Field(default=None, description="The completion token count.")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp showing when the report was synthesized.",
    )
    execution_id: Optional[str] = Field(default=None, description="Observability identifier tracking the graph execution run.")

