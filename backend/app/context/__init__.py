"""Conversational context engine (PRODUCT-001).

Short-term, in-memory, session-scoped conversational context. Resolves
follow-up questions ("En yoğun bölüm hangisi?", "Bunlardan en yoğun olan
kim?") into self-contained questions before the NLU pipeline runs.

Deliberately independent from Analytics, SQL generation, and RAG:
no persistence, no embeddings, no database access.
"""

from app.context.context_manager import ContextManager
from app.context.models import (
    ConversationContext,
    ConversationTurn,
    ExtractedSignals,
    ResolutionResult,
)
from app.context.session_store import DEFAULT_SESSION_ID, generate_session_id

__all__ = [
    "ContextManager",
    "ConversationContext",
    "ConversationTurn",
    "ExtractedSignals",
    "ResolutionResult",
    "DEFAULT_SESSION_ID",
    "generate_session_id",
]
