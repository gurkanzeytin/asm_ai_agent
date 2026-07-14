from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ExtractedSignals(BaseModel):
    """Deterministic context signals detected in a single user question."""

    date_expression: Optional[str] = Field(
        default=None,
        description="Raw temporal expression as the user wrote it (e.g. 'bugün', 'geçen hafta').",
    )
    department: Optional[str] = Field(
        default=None, description="Canonical department name mentioned in the question."
    )
    entity_types: List[str] = Field(
        default_factory=list,
        description="Domain entity types mentioned (Doctor, Patient, Appointment, ...).",
    )
    pronouns: List[str] = Field(
        default_factory=list,
        description="Referential pronouns found ('bunlardan', 'onlar', 'o bölüm', ...).",
    )
    analysis_type: Optional[str] = Field(
        default=None,
        description="Detected analysis style: ranking | comparison | trend | count | list.",
    )
    is_analytical: bool = Field(
        default=False,
        description="Whether the question carries an aggregate/ranking/count cue.",
    )
    asks_department: bool = Field(
        default=False,
        description="Whether the question itself asks about departments (blocks department inheritance).",
    )
    is_date_only_followup: bool = Field(
        default=False,
        description="Whether the question is only a new date filter (e.g. 'Peki geçen ay?').",
    )


class ConversationTurn(BaseModel):
    """One user interaction retained in the short-term context window."""

    question: str = Field(..., description="Original user question.")
    resolved_question: str = Field(..., description="Question after context resolution.")
    signals: ExtractedSignals = Field(
        default_factory=ExtractedSignals, description="Signals extracted from the resolved question."
    )


class ConversationContext(BaseModel):
    """Short-term conversational state for a single chat session.

    Holds only the latest explicit filters — each new explicit user statement
    replaces the previous value of the same type (context expiration rule).
    """

    session_id: str = Field(..., description="Opaque session key.")
    date_expression: Optional[str] = Field(
        default=None, description="Latest explicit temporal filter expression."
    )
    department: Optional[str] = Field(
        default=None, description="Latest explicitly mentioned department."
    )
    entity_types: List[str] = Field(
        default_factory=list, description="Entity types from the latest entity-bearing question."
    )
    analysis_type: Optional[str] = Field(
        default=None, description="Latest detected analysis style."
    )
    last_question: Optional[str] = Field(
        default=None, description="Most recent resolved question (used for date-only follow-ups)."
    )
    turns: List[ConversationTurn] = Field(
        default_factory=list, description="Sliding window of recent interactions."
    )
    updated_at: float = Field(
        default=0.0, description="Monotonic-ish wall-clock timestamp of the last interaction."
    )

    def is_empty(self) -> bool:
        """Returns True when no inheritable context has been accumulated yet."""
        return not (
            self.date_expression
            or self.department
            or self.entity_types
            or self.last_question
        )


class ResolutionResult(BaseModel):
    """Outcome of resolving one question against the session context."""

    original_question: str = Field(..., description="Question exactly as the user typed it.")
    resolved_question: str = Field(..., description="Context-enriched question sent to the NLU pipeline.")
    inherited: Dict[str, str] = Field(
        default_factory=dict,
        description="Filters inherited from context, keyed by type (date, department, referent, ...).",
    )
    confidence: float = Field(
        default=1.0, description="Deterministic confidence of the applied resolution."
    )
    applied: bool = Field(
        default=False, description="Whether any context enrichment was applied."
    )
    clarification_needed: bool = Field(
        default=False, description="Whether the follow-up is ambiguous and needs clarification."
    )
    clarification_question: Optional[str] = Field(
        default=None, description="Clarification question to surface to the user."
    )
    clarification_options: List[str] = Field(
        default_factory=list, description="Candidate referents offered to the user."
    )
