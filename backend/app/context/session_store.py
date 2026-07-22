import threading
import time
import uuid
from typing import Callable, Dict

from app.context.models import ConversationContext

DEFAULT_SESSION_ID = "default"


def generate_session_id() -> str:
    """Generates a safe, opaque, ephemeral session identifier.

    UUID4-based: carries no patient, user, email, or other PII. Used whenever
    a caller omits session_id — never fall back to sharing DEFAULT_SESSION_ID
    across unrelated requests/conversations.
    """
    return f"sess-{uuid.uuid4()}"

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
        """Returns a snapshot copy of a session's context, or a fresh one if absent/expired.

        Always returns a deep copy — callers may freely mutate the result without
        risking corruption of the store's internal state (see `update()` for the
        atomic read-modify-write path used by conversational updates).
        """
        with self._lock:
            context = self._get_live_or_fresh(session_id)
            return context.model_copy(deep=True)

    def _get_live_or_fresh(self, session_id: str) -> ConversationContext:
        """Internal: returns the live (not copied) context. Caller must hold `self._lock`."""
        context = self._sessions.get(session_id)
        if context is None or self._expired(context):
            context = ConversationContext(session_id=session_id, updated_at=self._now())
            self._sessions[session_id] = context
        return context

    def save(self, context: ConversationContext) -> None:
        """Stores the updated context, trimming the turn window and refreshing the TTL."""
        with self._lock:
            context.updated_at = self._now()
            if len(context.turns) > self._max_turns:
                context.turns = context.turns[-self._max_turns :]
            self._sessions[context.session_id] = context

    def update(
        self, session_id: str, mutator: Callable[[ConversationContext], None]
    ) -> ConversationContext:
        """Atomically reads, mutates, and saves a session's context under one lock.

        `mutator` receives the live context (not a copy) and mutates it in place;
        this closes the read-modify-write race that a separate get()+save() pair
        has under concurrent requests for the same session — two overlapping
        updates can otherwise silently lose one side's changes ("last write wins"
        on the wrong write). Returns a snapshot copy of the result.

        Process-local only: this lock only serializes writes within a single
        Python process. Running multiple backend processes/workers each holds
        its own independent SessionStore, so cross-process consistency would
        require an external store (see module docstring / class docstring).
        """
        with self._lock:
            context = self._get_live_or_fresh(session_id)
            mutator(context)
            context.updated_at = self._now()
            if len(context.turns) > self._max_turns:
                context.turns = context.turns[-self._max_turns :]
            self._sessions[session_id] = context
            return context.model_copy(deep=True)

    def clear(self, session_id: str) -> bool:
        """Drops all context for a session (new-conversation reset).

        Idempotent: clearing an already-absent/unknown session is a no-op that
        still returns successfully. Returns True when a session actually existed
        and was removed, False when there was nothing to clear.
        """
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
            return existed

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def turn_count(self, session_id: str) -> int:
        """Returns the current retained turn count for a session (0 if absent/expired)."""
        with self._lock:
            context = self._sessions.get(session_id)
            if context is None or self._expired(context):
                return 0
            return len(context.turns)

    def is_expired_or_absent(self, session_id: str) -> bool:
        """True when the session has no live (non-expired) context."""
        with self._lock:
            context = self._sessions.get(session_id)
            return context is None or self._expired(context)

    def _expired(self, context: ConversationContext) -> bool:
        return (self._now() - context.updated_at) > self._ttl_seconds
