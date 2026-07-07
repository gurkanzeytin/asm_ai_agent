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

class ReportResponse(BaseModel):
    """API response payload returned by the AI report generation endpoint."""

    success: bool = Field(..., description="Indicates whether the workflow completed without errors.")
    workflow_id: Optional[str] = Field(default=None, description="Unique identifier for the workflow execution run.")
    question: str = Field(..., description="The original user question echoed back.")
    generated_sql: Optional[str] = Field(default=None, description="SQL statement generated and executed during the workflow.")
    query_result: Optional[QueryResultSchema] = Field(default=None, description="Structured database result set.")
    report: Optional[ReportSchema] = Field(default=None, description="Generated narrative report.")
    metadata: Optional[MetadataSchema] = Field(default=None, description="LLM execution observability metadata.")

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
]
