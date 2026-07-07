from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class GeneratedSQL(BaseModel):
    """Shared application DTO model representing safety validated generated SQL metadata."""

    model_config = ConfigDict(frozen=True)

    sql: str = Field(..., description="The raw generated and parsed SQL query.")
    normalized_sql: Optional[str] = Field(default=None, description="The AST-normalized query format.")
    validation_result: Optional[Any] = Field(default=None, description="The safety validator result output.")
    provider: str = Field(..., description="The LLM provider name identifier.")
    model: str = Field(..., description="The target LLM model identifier.")
    latency_ms: float = Field(..., description="The generation execution time in milliseconds.")
    prompt_tokens: Optional[int] = Field(default=None, description="The prompt token count.")
    completion_tokens: Optional[int] = Field(default=None, description="The completion token count.")
