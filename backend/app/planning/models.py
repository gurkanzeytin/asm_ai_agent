from typing import List, Optional

from pydantic import BaseModel, Field


class JoinStep(BaseModel):
    """One foreign-key hop on the minimal join path."""

    from_table: str = Field(..., description="Table owning the foreign key column.")
    from_column: str = Field(..., description="Foreign key column name.")
    to_table: str = Field(..., description="Referenced table name.")
    to_column: str = Field(..., description="Referenced (usually primary key) column name.")

    def render(self) -> str:
        return f"{self.from_table}.{self.from_column} -> {self.to_table}.{self.to_column}"


class DateFilterPlan(BaseModel):
    """A temporal constraint carried into the plan."""

    expression: str = Field(..., description="Original temporal wording (e.g. 'bugun').")
    start_date: str = Field(..., description="ISO start date of the range.")
    end_date: str = Field(..., description="ISO end date of the range.")
    column: Optional[str] = Field(
        default=None, description="Date column on the fact table, when one is discoverable."
    )


class QueryPlan(BaseModel):
    """Deterministic contract between NLU and SQL generation (AG-022).

    Organizes every constraint the NLU extracted so none silently disappears
    between question understanding and SQL generation. Never contains SQL.
    """

    question: str = Field(..., description="Question the plan was built from.")
    output_entity: Optional[str] = Field(
        default=None, description="Entity type the user wants returned (e.g. Doctor)."
    )
    fact_entity: Optional[str] = Field(
        default=None, description="Entity type being filtered/aggregated over (e.g. Appointment)."
    )
    output_table: Optional[str] = Field(
        default=None, description="Schema table backing the output entity."
    )
    fact_table: Optional[str] = Field(
        default=None, description="Schema table backing the fact entity."
    )
    date_filters: List[DateFilterPlan] = Field(
        default_factory=list, description="Temporal constraints, already resolved to ISO ranges."
    )
    department_filter: Optional[str] = Field(
        default=None, description="Department name constraint, as stored in the database."
    )
    extra_filters: List[str] = Field(
        default_factory=list,
        description="Additional textual constraints that must survive (e.g. negation).",
    )
    aggregation: Optional[str] = Field(
        default=None, description="Required aggregate function: COUNT, SUM, or AVG."
    )
    ranking: Optional[str] = Field(
        default=None, description="Required ranking direction: DESC or ASC."
    )
    limit: Optional[int] = Field(default=None, description="Explicit LIMIT requested.")
    order: Optional[str] = Field(default=None, description="Explicit ordering direction.")
    analysis_type: Optional[str] = Field(
        default=None, description="ranking | comparison | trend | count | list."
    )
    join_path: List[JoinStep] = Field(
        default_factory=list, description="Minimal FK path connecting fact, output, and filters."
    )
    projection: List[str] = Field(
        default_factory=list, description="Descriptive column(s) the SELECT must return."
    )
    distinct: bool = Field(
        default=False, description="Whether the output requires DISTINCT rows."
    )
    planner_ms: float = Field(default=0.0, description="Planning duration in milliseconds.")

    def constraint_count(self) -> int:
        """Number of hard constraints the plan carries (used for logging)."""
        return (
            len(self.date_filters)
            + (1 if self.department_filter else 0)
            + len(self.extra_filters)
            + (1 if self.aggregation else 0)
            + (1 if self.ranking else 0)
            + (1 if self.limit else 0)
        )


class ComplianceResult(BaseModel):
    """Outcome of validating generated SQL against a QueryPlan."""

    compliant: bool = Field(..., description="True when no planned constraint is missing.")
    missing: List[str] = Field(
        default_factory=list, description="Human-readable list of missing constraints."
    )
