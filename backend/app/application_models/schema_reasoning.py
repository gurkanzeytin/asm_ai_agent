"""Typed contract produced by bounded LLM schema reasoning."""

from typing import Literal

from pydantic import BaseModel, Field


class SchemaReasoningDecision(BaseModel):
    status: Literal["answerable", "out_of_scope"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    supporting_columns: list[str] = Field(default_factory=list)
    supporting_metrics: list[str] = Field(default_factory=list)
    dimension_columns: list[str] = Field(default_factory=list, max_length=2)
    analysis_type: str | None = None
    time_column: str | None = None
    time_scope: Literal[
        "all_time",
        "current_day",
        "previous_day",
        "current_week",
        "previous_week",
        "current_month",
        "previous_month",
        "current_year",
        "previous_year",
        "last_7_days",
        "last_30_days",
    ] | None = None
    grouping_granularity: Literal["hour", "day", "week", "month", "year"] | None = None
    order: Literal["ASC", "DESC"] | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    assumptions: list[str] = Field(default_factory=list, max_length=5)

    @property
    def approved(self) -> bool:
        return self.status == "answerable" and self.confidence >= 0.70

    @property
    def typed_plan_ready(self) -> bool:
        return self.approved and bool(self.supporting_metrics and self.analysis_type)
