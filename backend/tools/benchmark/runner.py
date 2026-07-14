"""Benchmark runner: executes every dataset question against every model.

One question failure never stops the run; every outcome is recorded.
"""

import asyncio
import logging
import time

from tools.benchmark.config import BenchmarkConfig
from tools.benchmark.dataset import BenchmarkQuestion, load_dataset
from tools.benchmark.metrics import Outcome, QuestionRun, Reason, classify
from tools.benchmark.models import (
    ModelPipeline,
    build_pipeline,
    installed_ollama_models,
    is_model_available,
)

logger = logging.getLogger(__name__)

# Report providers that indicate a dedicated report LLM call was made.
_LLM_REPORT_PROVIDERS = {"ollama", "gemini"}


class ProgressPrinter:
    """Console progress with elapsed time and a linear ETA."""

    def __init__(self, total_steps: int):
        self.total_steps = total_steps
        self.done = 0
        self.started = time.perf_counter()

    def step(self, model: str, question: BenchmarkQuestion, repeat_index: int) -> None:
        self.done += 1
        elapsed = time.perf_counter() - self.started
        eta = (elapsed / self.done) * (self.total_steps - self.done) if self.done else 0.0
        print(
            f"[{self.done}/{self.total_steps}] model={model} q{question.id} "
            f"({question.category}) rep={repeat_index + 1} "
            f"elapsed={elapsed:.0f}s eta={eta:.0f}s",
            flush=True,
        )


async def run_question(
    pipeline: ModelPipeline,
    question: BenchmarkQuestion,
    repeat_index: int,
    timeout_s: float,
) -> QuestionRun:
    """Runs one question through the workflow and converts it to a QuestionRun."""
    run = QuestionRun(
        model=pipeline.model,
        question_id=question.id,
        category=question.category,
        question=question.question,
        repeat_index=repeat_index,
    )
    calls_before, timeouts_before, ptok_before, ctok_before, reasons_before = (
        pipeline.provider.log.snapshot()
    )
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            pipeline.reporting_service.run_workflow(question.question),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        run.total_ms = (time.perf_counter() - start) * 1000
        run.exception = f"question timeout after {timeout_s}s"
        run.outcome, run.reason = Outcome.FAILED.value, Reason.TIMEOUT.value
        _apply_llm_deltas(run, pipeline, calls_before, timeouts_before, ptok_before, ctok_before, reasons_before)
        return run
    except Exception as e:  # noqa: BLE001 — the benchmark must never stop.
        run.total_ms = (time.perf_counter() - start) * 1000
        run.exception = f"{type(e).__name__}: {e}"
        outcome, reason = classify(run)
        run.outcome, run.reason = outcome.value, reason.value
        _apply_llm_deltas(run, pipeline, calls_before, timeouts_before, ptok_before, ctok_before, reasons_before)
        return run

    run.total_ms = (time.perf_counter() - start) * 1000
    run.generated_sql = result.generated_sql
    run.errors = list(result.errors or [])
    if result.query_result is not None:
        run.execution_success = bool(result.query_result.success)
        run.rows_returned = int(result.query_result.row_count)
    run.analytics_generated = result.analytics is not None
    run.insight_generated = result.insights is not None
    run.report_generated = result.generated_report is not None

    if result.metrics:
        run.sql_generation_ms = result.metrics.generate_sql_ms or 0.0
        run.analytics_ms = result.metrics.analyze_results_ms or 0.0
        run.insight_ms = result.metrics.generate_insights_ms or 0.0
        run.report_ms = result.metrics.generate_report_ms or 0.0

    _apply_llm_deltas(run, pipeline, calls_before, timeouts_before, ptok_before, ctok_before, reasons_before)

    # SQL-generation retries: LLM calls beyond the expected one-per-stage baseline.
    baseline = 0
    if run.generated_sql or any("GenerateSQLNode" in error for error in run.errors):
        baseline += 1
    if result.insights is not None and result.insights.llm_generated:
        baseline += 1
    if (
        result.generated_report is not None
        and result.generated_report.provider in _LLM_REPORT_PROVIDERS
    ):
        baseline += 1
    run.retry_count = max(0, run.llm_calls - baseline) if run.llm_calls else 0

    # Errors on the state mean a node degraded; classification decides severity.
    if run.errors and not run.generated_sql:
        sql_errors = [error for error in run.errors if "SQL" in error or "GenerateSQLNode" in error]
        if sql_errors:
            run.generated_sql = None  # explicit: SQL stage failed

    outcome, reason = classify(run)
    run.outcome, run.reason = outcome.value, reason.value
    return run


def _apply_llm_deltas(
    run: QuestionRun,
    pipeline: ModelPipeline,
    calls_before: int,
    timeouts_before: int,
    ptok_before: int,
    ctok_before: int,
    reasons_before: int,
) -> None:
    log = pipeline.provider.log
    run.llm_calls = log.calls - calls_before
    run.llm_timeouts = log.timeouts - timeouts_before
    run.prompt_tokens = log.prompt_tokens - ptok_before
    run.completion_tokens = log.completion_tokens - ctok_before
    run.finish_reasons = list(log.finish_reasons[reasons_before:])


async def run_benchmark(config: BenchmarkConfig) -> tuple[list[QuestionRun], list[str]]:
    """Runs the full benchmark matrix. Returns (all runs, skipped models)."""
    from app.core.config import settings

    questions = load_dataset(config.dataset_path, config.categories, config.limit)
    installed = installed_ollama_models(settings.OLLAMA_BASE_URL)

    available = [m for m in config.models if is_model_available(m, installed)]
    skipped = [m for m in config.models if m not in available]
    for model in skipped:
        print(f"SKIP: model '{model}' is not installed in Ollama (ollama pull {model})", flush=True)
    if not available:
        raise RuntimeError("None of the requested models are installed in Ollama.")

    total_steps = len(available) * len(questions) * config.repeat
    progress = ProgressPrinter(total_steps)
    all_runs: list[QuestionRun] = []

    for model in available:
        print(f"\n=== Model: {model} ({len(questions)} questions x{config.repeat}) ===", flush=True)
        pipeline = build_pipeline(model)
        try:
            for question in questions:
                for repeat_index in range(config.repeat):
                    run = await run_question(
                        pipeline, question, repeat_index, config.question_timeout_s
                    )
                    all_runs.append(run)
                    progress.step(model, question, repeat_index)
                    logger.info(
                        "benchmark run: model=%s q=%s outcome=%s reason=%s total_ms=%.0f",
                        model, question.id, run.outcome, run.reason, run.total_ms,
                    )
        finally:
            await pipeline.provider.close()

    return all_runs, skipped
