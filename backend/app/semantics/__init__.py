"""Semantic Understanding Engine (REASONING-001).

Deterministic semantic interpretation layer running before every
database-related decision. Produces a structured SemanticFrame — the user's
goal, subjects, constraints, question type, relationships, ambiguities, and
confidence — which feeds the Query Planner and routing decisions.

No LLM calls, no embeddings, no vector search, no SQL awareness.
"""

from app.semantics.engine import SemanticUnderstandingEngine
from app.semantics.models import (
    SemanticAmbiguity,
    SemanticConstraint,
    SemanticFrame,
    SemanticRelationship,
)

__all__ = [
    "SemanticAmbiguity",
    "SemanticConstraint",
    "SemanticFrame",
    "SemanticRelationship",
    "SemanticUnderstandingEngine",
]
