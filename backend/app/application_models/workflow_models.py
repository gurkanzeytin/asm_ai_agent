from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.application_models.generated_report import GeneratedReport
from app.application_models.generated_sql import GeneratedSQL


class WorkflowExecutionResult(BaseModel):
    """Shared DTO model representing overall workflow orchestrations results."""

    model_config = ConfigDict(frozen=True)

    question: str = Field(..., description="The query parameter.")
    generated_sql: Optional[GeneratedSQL] = Field(default=None, description="The SQL generation details.")
    generated_report: Optional[GeneratedReport] = Field(
        default=None, description="The narrative report summary details."
    )
