import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_context_manager
from app.context import ContextManager

logger = logging.getLogger(__name__)

router = APIRouter()


class ContextResetResponse(BaseModel):
    """Response payload for a conversational-memory reset."""

    session_id: str = Field(..., description="Session key that was targeted.")
    memory_reset: bool = Field(
        ..., description="Whether a live session actually existed and was cleared."
    )


@router.delete(
    "/{session_id}",
    response_model=ContextResetResponse,
    summary="Reset one conversational session's memory",
    description=(
        "Clears the short-term conversational context for exactly one session — never "
        "any other session. Missing/unknown session IDs are handled idempotently: the "
        "call still succeeds and reports memory_reset=false."
    ),
)
async def reset_context(
    session_id: str,
    context_manager: Annotated[ContextManager, Depends(get_context_manager)],
) -> ContextResetResponse:
    """Clears one session's conversational memory (new-conversation reset)."""
    existed = context_manager.clear(session_id)
    logger.info(
        "Conversational context reset requested.",
        extra={"session_id": session_id, "memory_reset": existed},
    )
    return ContextResetResponse(session_id=session_id, memory_reset=existed)
