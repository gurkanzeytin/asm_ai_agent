from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class GeneratedReport(BaseModel):
    """Shared application DTO model representing summarized report narrative outputs."""

    model_config = ConfigDict(frozen=True)

    title: Optional[str] = Field(default=None, description="The extracted report title header.")
    summary: Optional[str] = Field(default=None, description="The extracted executive summary.")
    markdown: str = Field(..., description="The narrative content in markdown formatting.")
    tables: Optional[List[Any]] = Field(default=None, description="Structured parsed report tables.")
    charts: Optional[List[Any]] = Field(default=None, description="Structured parsed report charts.")
