"""Request-scoped workflow progress reporting for the agent graph."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from typing import Any

ProgressCallback = Callable[[str], Awaitable[None]]

_progress_callback: ContextVar[ProgressCallback | None] = ContextVar(
    "workflow_progress_callback", default=None
)


def set_progress_callback(callback: ProgressCallback | None) -> Token:
    return _progress_callback.set(callback)


def reset_progress_callback(token: Token) -> None:
    _progress_callback.reset(token)


async def emit_progress(stage: str) -> None:
    callback = _progress_callback.get()
    if callback is not None:
        await callback(stage)


def with_progress(stage: str, node: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
    """Wraps a graph node without changing its state contract."""

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        await emit_progress(stage)
        result = node(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    return wrapped
