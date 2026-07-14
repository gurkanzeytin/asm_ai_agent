from typing import List, Optional

from pydantic import BaseModel, Field


class SemanticConstraint(BaseModel):
    """One semantic constraint extracted from the question."""

    type: str = Field(..., description="Constraint category: date, department, doctor, patient, negation, limit, ...")
    value: str = Field(..., description="Constraint value (canonical where possible).")
    detail: Optional[str] = Field(
        default=None, description="Extra machine-readable detail (e.g. ISO date range)."
    )


class SemanticAmbiguity(BaseModel):
    """A semantically ambiguous phrase, with the reason it cannot be resolved."""

    phrase: str = Field(..., description="The ambiguous wording as detected.")
    reason: str = Field(..., description="Why the phrase is ambiguous — never guessed.")


class SemanticRelationship(BaseModel):
    """A domain relationship between two subjects (semantic, not a SQL join)."""

    subject: str = Field(..., description="Source entity type.")
    predicate: str = Field(..., description="Semantic relation (works_in, belongs_to, ...).")
    object: str = Field(..., description="Target entity type.")

    def render(self) -> str:
        return f"{self.subject} --{self.predicate}--> {self.object}"


class SemanticFrame(BaseModel):
    """Structured semantic representation of the user's request (REASONING-001).

    This is the contract between semantic understanding and the Query Planner:
    every meaningful concept in the question must appear here in structured
    form, and no constraint may silently disappear.
    """

    question: str = Field(..., description="Original question.")
    normalized_question: str = Field(default="", description="NLU-normalized question.")
    goal: Optional[str] = Field(
        default=None,
        description="User goal: LIST, COUNT, COMPARE, ANALYZE, RANK, SUMMARIZE, TREND, FIND, AGGREGATE.",
    )
    primary_subject: Optional[str] = Field(
        default=None, description="Main entity the user asks about (e.g. Doctor)."
    )
    fact_subject: Optional[str] = Field(
        default=None,
        description="Entity being filtered/aggregated over when it differs from the primary subject.",
    )
    secondary_subjects: List[str] = Field(
        default_factory=list, description="Other entities involved in the request."
    )
    requested_output: Optional[str] = Field(
        default=None,
        description="What the user wants back: doctor_names, count, ranking, time_series, ...",
    )
    constraints: List[SemanticConstraint] = Field(
        default_factory=list, description="Every semantic constraint detected."
    )
    question_type: str = Field(
        default="information_retrieval",
        description=(
            "information_retrieval | aggregation | comparison | trend | ranking | "
            "distribution | negative | existence | analytical | follow_up | "
            "general_help | out_of_scope"
        ),
    )
    relationships: List[SemanticRelationship] = Field(
        default_factory=list, description="Semantic relationships among detected subjects."
    )
    ambiguities: List[SemanticAmbiguity] = Field(
        default_factory=list, description="Detected semantic ambiguities with reasons."
    )
    confidence: float = Field(
        default=0.5, description="Deterministic confidence of the interpretation [0..1]."
    )
    duration_ms: float = Field(default=0.0, description="Semantic analysis duration.")

    def constraint_types(self) -> List[str]:
        return [constraint.type for constraint in self.constraints]
