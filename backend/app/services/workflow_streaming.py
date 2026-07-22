"""Application-layer streaming orchestration for reporting workflows."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass

from app.application_models.workflow_result import WorkflowResult
from app.services.reporting_service import ReportingService


@dataclass(frozen=True)
class WorkflowStreamEvent:
    kind: str
    stage: str | None = None
    result: WorkflowResult | None = None
    error: Exception | None = None


async def stream_workflow(
    service: ReportingService,
    question: str,
    session_id: str,
) -> AsyncIterator[WorkflowStreamEvent]:
    """Yields real graph progress followed by exactly one terminal event."""

    queue: asyncio.Queue[WorkflowStreamEvent] = asyncio.Queue()

    async def on_progress(stage: str) -> None:
        await queue.put(WorkflowStreamEvent(kind="progress", stage=stage))

    async def run() -> None:
        try:
            result = await service.run_workflow(
                question,
                session_id=session_id,
                progress_callback=on_progress,
            )
            await queue.put(WorkflowStreamEvent(kind="complete", result=result))
        except Exception as error:
            await queue.put(WorkflowStreamEvent(kind="error", error=error))

    task = asyncio.create_task(run())
    try:
        while True:
            event = await queue.get()
            yield event
            if event.kind in {"complete", "error"}:
                break
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task
