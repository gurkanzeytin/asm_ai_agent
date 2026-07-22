"""Semantic Understanding Engine (REASONING-001).

Deterministic semantic interpretation layer running before every
database-related decision. Produces a structured SemanticFrame — the user's
goal, subjects, constraints, question type, relationships, ambiguities, and
confidence — which feeds the Query Planner and routing decisions.

No LLM calls, no embeddings, no vector search, no SQL awareness.
"""

from app.semantics.models import (
    SemanticAmbiguity,
    SemanticConstraint,
    SemanticFrame,
    SemanticRelationship,
)


def __getattr__(name: str):
    """Lazily expose the engine without creating a bootstrap import cycle."""
    if name == "SemanticUnderstandingEngine":
        from app.semantics.engine import SemanticUnderstandingEngine

        return SemanticUnderstandingEngine
    raise AttributeError(name)

__all__ = [
    "SemanticAmbiguity",
    "SemanticConstraint",
    "SemanticFrame",
    "SemanticRelationship",
    "SemanticUnderstandingEngine",
]
