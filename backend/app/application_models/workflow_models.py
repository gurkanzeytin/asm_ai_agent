from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.application_models.generated_report import GeneratedReport
from app.application_models.generated_sql import GeneratedSQL


class QueryResult(BaseModel):
    """Structured DTO representing executed SQL query results."""

    model_config = ConfigDict(frozen=True)

    columns: List[str] = Field(..., description="Ordered list of column names in the result set.")
    rows: List[Dict[str, Any]] = Field(..., description="List of rows represented as key-value dictionaries.")
    row_count: int = Field(..., description="Total count of rows returned.")
    execution_time_ms: float = Field(..., description="Time taken to execute query in milliseconds.")
    success: bool = Field(..., description="Flag indicating whether query execution was successful.")
    executed_at: datetime = Field(..., description="Timestamp showing when query execution occurred.")
    database_provider: str = Field(..., description="Target database engine provider name.")
    source_record_count: Optional[int] = Field(
        default=None,
        description="Underlying business-record count only when genuinely known.",
    )
    result_group_count: Optional[int] = Field(
        default=None,
        description="Number of analytical groups only when the complete group set is known.",
    )
    returned_row_count: Optional[int] = Field(
        default=None,
        description="Rows retained at the current execution/presentation boundary.",
    )
    displayed_row_count: Optional[int] = Field(
        default=None,
        description="Rows intended for one user-visible page.",
    )
    result_truncated: bool = Field(
        default=False,
        description="Whether any upstream or current boundary removed additional rows.",
    )
    applied_limit: Optional[int] = Field(
        default=None,
        description="Hard row limit applied at the current boundary.",
    )
    has_more: bool = Field(
        default=False,
        description="Whether at least one additional row is known to exist.",
    )
    total_count: Optional[int] = Field(
        default=None,
        description="Exact total only when already known; never triggers an implicit COUNT query.",
    )
    unsafe_detail_output: bool = Field(
        default=False,
        description="Oversized identifier-bearing analytical detail blocked from presentation.",
    )


class WorkflowExecutionResult(BaseModel):
    """Shared DTO model representing overall workflow orchestrations results."""

    model_config = ConfigDict(frozen=True)

    question: str = Field(..., description="The query parameter.")
    generated_sql: Optional[GeneratedSQL] = Field(default=None, description="The SQL generation details.")
    query_result: Optional[QueryResult] = Field(default=None, description="The SQL execution query results.")
    generated_report: Optional[GeneratedReport] = Field(
        default=None, description="The narrative report summary details."
    )
