import threading
import time
from typing import Callable, Dict

from app.context.models import ConversationContext

DEFAULT_SESSION_ID = "default"

# Context lifetime. Without a frontend "new conversation" signal, inactivity
# is the deterministic proxy: a session idle longer than the TTL starts fresh.
DEFAULT_TTL_SECONDS = 30 * 60

# Sliding window of retained interactions per session.
DEFAULT_MAX_TURNS = 8


class SessionStore:
    """Thread-safe, in-memory store of per-session conversational context.

    Deliberately volatile: nothing is persisted, nothing survives a process
    restart, and expired sessions are replaced by empty contexts.
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_turns: int = DEFAULT_MAX_TURNS,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_turns = max_turns
        self._now = now_fn or time.time
        self._sessions: Dict[str, ConversationContext] = {}
        self._lock = threading.Lock()

    @property
    def max_turns(self) -> int:
        return self._max_turns

    def get(self, session_id: str) -> ConversationContext:
        """Returns the live context for a session, or a fresh one if absent/expired."""
        with self._lock:
            context = self._sessions.get(session_id)
            if context is None or self._expired(context):
                context = ConversationContext(session_id=session_id, updated_at=self._now())
                self._sessions[session_id] = context
            return context.model_copy(deep=True)

    def save(self, context: ConversationContext) -> None:
        """Stores the updated context, trimming the turn window and refreshing the TTL."""
        with self._lock:
            context.updated_at = self._now()
            if len(context.turns) > self._max_turns:
                context.turns = context.turns[-self._max_turns :]
            self._sessions[context.session_id] = context

    def clear(self, session_id: str) -> None:
        """Drops all context for a session (new-conversation reset)."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _expired(self, context: ConversationContext) -> bool:
        return (self._now() - context.updated_at) > self._ttl_seconds
