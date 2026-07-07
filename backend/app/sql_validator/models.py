from typing import List, Optional
from pydantic import BaseModel, Field


class SQLValidationResult(BaseModel):
    """Pydantic model representing structured output from safety checks."""

    valid: bool = Field(..., description="Flag indicating if query passes safety metrics.")
    normalized_sql: Optional[str] = Field(
        default=None, description="The formatted, normalized representation of safe SQL."
    )
    statement_type: Optional[str] = Field(
        default=None, description="The parsed SQL statement type (e.g. SELECT, UNION)."
    )
    reason: Optional[str] = Field(
        default=None, description="Diagnostic error details explaining any rejection."
    )
    warnings: List[str] = Field(
        default_factory=list, description="Non-blocking warning messages produced."
    )
