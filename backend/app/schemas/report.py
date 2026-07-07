from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    """Pydantic schema driving user request reports payload."""

    query: str = Field(..., description="Natural language question targeting database query.")


class ReportResponse(BaseModel):
    """Pydantic schema returning compiled query report details."""

    query: str
    sql_query: str | None = Field(default=None, description="Generated SQL statement.")
    query_result: list[dict] | None = Field(default=None, description="Database output records.")
    report: str | None = Field(default=None, description="Narrative markdown summary report.")
    error: str | None = Field(default=None, description="Captured processing error logs.")
