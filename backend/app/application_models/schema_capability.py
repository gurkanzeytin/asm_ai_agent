from pydantic import BaseModel, ConfigDict, Field


class SchemaCapabilityAnswer(BaseModel):
    """Deterministic, non-SQL answer to a question about one schema column."""

    model_config = ConfigDict(frozen=True)

    column: str = Field(..., description="Canonical column name from the catalog.")
    business_name: str = Field(..., description="User-facing Turkish column label.")
    markdown: str = Field(..., description="Safe catalog-derived capability explanation.")
    protected: bool = Field(
        default=False,
        description="Whether raw values are protected by PII/selectability policy.",
    )
