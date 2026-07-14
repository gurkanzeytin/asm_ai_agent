import logging

from app.context.extractor import ContextExtractor
from app.context.models import ConversationTurn, ResolutionResult
from app.context.resolver import ContextResolver
from app.context.session_store import DEFAULT_SESSION_ID, SessionStore

logger = logging.getLogger(__name__)


class ContextManager:
    """Facade of the conversational context engine.

    resolve() runs before the NLU pipeline and rewrites follow-up questions
    into self-contained ones; update() runs after the workflow and records
    the latest explicit filters. Both degrade to no-ops on any internal
    failure — the context engine must never break the main pipeline.
    """

    def __init__(
        self,
        store: SessionStore | None = None,
        extractor: ContextExtractor | None = None,
        resolver: ContextResolver | None = None,
    ) -> None:
        self._store = store or SessionStore()
        self._extractor = extractor or ContextExtractor()
        self._resolver = resolver or ContextResolver(self._extractor)

    def resolve(
        self, question: str, session_id: str = DEFAULT_SESSION_ID
    ) -> ResolutionResult:
        """Resolves a question against the session context. Never raises."""
        try:
            context = self._store.get(session_id)
            result = self._resolver.resolve(question, context)
        except Exception as error:  # degrade, never break the pipeline
            logger.error("ContextManager.resolve failed: %s", error)
            return ResolutionResult(
                original_question=question, resolved_question=question
            )

        logger.info(
            "Conversational context resolution: session=%s applied=%s "
            "clarification=%s confidence=%.2f\n"
            "  Original : %s\n"
            "  Resolved : %s\n"
            "  Inherited: %s",
            session_id,
            result.applied,
            result.clarification_needed,
            result.confidence,
            result.original_question,
            result.resolved_question,
            result.inherited or "none",
            extra={
                "session_id": session_id,
                "original_question": result.original_question,
                "resolved_question": result.resolved_question,
                "inherited_filters": result.inherited,
                "confidence": result.confidence,
                "clarification_required": result.clarification_needed,
            },
        )
        return result

    def update(
        self, resolution: ResolutionResult, session_id: str = DEFAULT_SESSION_ID
    ) -> None:
        """Records the interaction and refreshes the session filters. Never raises."""
        try:
            if resolution.clarification_needed:
                return

            context = self._store.get(session_id)
            signals = self._extractor.extract(resolution.resolved_question)

            # Latest explicit statement replaces the previous filter of the
            # same type (context expiration rule). Untouched types persist.
            if signals.date_expression:
                context.date_expression = signals.date_expression
            if signals.department:
                context.department = signals.department
            if signals.entity_types:
                context.entity_types = signals.entity_types
            if signals.analysis_type:
                context.analysis_type = signals.analysis_type

            # Only content-bearing questions become the continuation anchor;
            # greetings/small talk must not hijack "Peki geçen ay?" follow-ups.
            if signals.entity_types or signals.is_analytical or signals.asks_department:
                context.last_question = resolution.resolved_question

            context.turns.append(
                ConversationTurn(
                    question=resolution.original_question,
                    resolved_question=resolution.resolved_question,
                    signals=signals,
                )
            )
            self._store.save(context)

            logger.info(
                "Conversational context updated: session=%s date=%s department=%s "
                "entities=%s analysis=%s turns=%d",
                session_id,
                context.date_expression,
                context.department,
                context.entity_types,
                context.analysis_type,
                len(context.turns),
                extra={
                    "session_id": session_id,
                    "context_date": context.date_expression,
                    "context_department": context.department,
                    "context_entities": context.entity_types,
                    "context_analysis_type": context.analysis_type,
                },
            )
        except Exception as error:  # degrade, never break the pipeline
            logger.error("ContextManager.update failed: %s", error)

    def clear(self, session_id: str = DEFAULT_SESSION_ID) -> None:
        """Clears the session context (new-conversation reset)."""
        self._store.clear(session_id)
