"""Safe, manual live comparison of insight-generation modes for one question.

Runs the full production pipeline (schema retrieval -> SQL generation -> SQL
execution -> deterministic analytics) exactly once against the real database
and LLM providers configured in .env, then generates the Insight Engine's
output for the SAME analytics result under four modes:

    deterministic  — no LLM call at all
    ollama         — forces the local qwen3 leg
    nvidia         — forces the remote DeepSeek leg (skipped if no API key)
    auto           — the real complexity-based router (production behavior)

Running each mode against the same already-computed analytics isolates the
insight-generation comparison from re-running SQL generation/execution four
times, while still exercising each real provider end to end.

This is a live, opt-in verification tool. It is NOT run automatically by the
test suite (no test imports or calls this module) and requires a real
database connection plus, for the ollama/nvidia/auto modes, a real LLM
provider. It never prints API keys, raw patient rows, or full prompts — only
a SHA-256 hash of the generated SQL and the same whitelisted fields the
Insight Engine itself is allowed to send to a remote provider.

Usage:
    cd backend
    python scripts/compare_insight_modes.py "Randevu durumlarının dağılımı nedir?"

Exits 0 on success (even if a mode is skipped/unavailable), non-zero only if
the base pipeline itself fails before any insight comparison can run.
"""

import asyncio
import hashlib
import sys
import time
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.agent.state import AgentState  # noqa: E402
from app.bootstrap import container  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.insights.insight_engine import InsightEngine  # noqa: E402
from app.insights.routing import InsightRouter  # noqa: E402
from app.llm.provider import LLMFactory  # noqa: E402

_DEFAULT_QUESTION = "Randevu durumlarının dağılımı nedir?"


def _redact_sql(sql: str | None) -> str:
    """Never prints the actual SQL text — only a hash and length, for correlation."""
    if not sql:
        return "<none>"
    digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest} ({len(sql)} chars)"


async def _run_base_pipeline(question: str):
    """Runs the real graph once, up through deterministic analytics."""
    return await container.agent_graph.ainvoke(
        AgentState(question=question, workflow_id="compare-insight-modes")
    )


async def _build_engine_for_mode(mode: str) -> tuple[InsightEngine | None, str | None]:
    """Returns (engine, skip_reason). skip_reason is set when a mode can't run."""
    if mode == "deterministic":
        return (
            InsightEngine(
                local_llm_provider=None,
                remote_llm_provider=None,
                router=InsightRouter(
                    enabled=True, deterministic_enabled=True, remote_available=False
                ),
            ),
            None,
        )

    if mode == "ollama":
        try:
            local = LLMFactory.get_provider("ollama")
        except Exception as e:
            return None, f"Ollama unavailable: {e}"
        return InsightEngine(local_llm_provider=local), None

    if mode == "nvidia":
        if not settings.NVIDIA_API_KEY.get_secret_value():
            return None, "NVIDIA_API_KEY not configured"
        try:
            remote = LLMFactory.get_provider("nvidia")
        except Exception as e:
            return None, f"NVIDIA unavailable: {e}"
        # Force remote regardless of computed complexity, to actually exercise it.
        router = InsightRouter(remote_complexity_threshold=0, remote_available=True)
        return InsightEngine(remote_llm_provider=remote, router=router), None

    if mode == "auto":
        local = None
        try:
            local = LLMFactory.get_provider("ollama")
        except Exception:
            pass
        remote = None
        if settings.NVIDIA_API_KEY.get_secret_value():
            try:
                remote = LLMFactory.get_provider("nvidia")
            except Exception:
                pass
        return InsightEngine(local_llm_provider=local, remote_llm_provider=remote), None

    return None, f"Unknown mode: {mode}"


async def _run_mode(mode: str, analytics) -> dict:
    engine, skip_reason = await _build_engine_for_mode(mode)
    if engine is None:
        return {"mode": mode, "skipped": skip_reason}

    start = time.perf_counter()
    try:
        result = await engine.generate(analytics)
    except Exception as e:
        return {"mode": mode, "exception": f"{type(e).__name__}: {e}"}
    elapsed_ms = (time.perf_counter() - start) * 1000

    return {
        "mode": mode,
        "elapsed_ms": round(elapsed_ms, 1),
        "selected_provider": result.provider,
        "selected_model": result.model,
        "routing_mode": result.routing_mode,
        "routing_reason": result.routing_reason,
        "llm_invoked": result.llm_generated,
        "llm_inference_ms": result.llm_latency_ms,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "finish_reason": result.finish_reason,
        "fallback_used": result.fallback_used,
        "fallback_reason": result.fallback_reason,
        "remote_data_policy": result.remote_data_policy,
        "final_answer": result.summary,
    }


def _print_result(entry: dict) -> None:
    print(f"\n--- Mode: {entry['mode']} ---")
    if "skipped" in entry:
        print(f"  Skipped           : {entry['skipped']}")
        return
    if "exception" in entry:
        print(f"  Exception         : {entry['exception']}")
        return
    print(f"  Elapsed ms        : {entry['elapsed_ms']}")
    print(f"  Selected provider : {entry['selected_provider']}")
    print(f"  Selected model    : {entry['selected_model']}")
    print(f"  Routing mode      : {entry['routing_mode']}")
    print(f"  Routing reason    : {entry['routing_reason']}")
    print(f"  LLM invoked       : {entry['llm_invoked']}")
    print(f"  LLM inference ms  : {entry['llm_inference_ms']}")
    print(f"  Prompt tokens     : {entry['prompt_tokens']}")
    print(f"  Completion tokens : {entry['completion_tokens']}")
    print(f"  Finish reason     : {entry['finish_reason']}")
    print(f"  Fallback used     : {entry['fallback_used']}")
    print(f"  Fallback reason   : {entry['fallback_reason']}")
    print(f"  Remote policy     : {entry['remote_data_policy']}")
    print(f"  Final answer      : {entry['final_answer']}")


async def main(question: str) -> int:
    print("===== INSIGHT MODE COMPARISON (live, manual) =====")
    print(f"Question           : {question}")

    pipeline_start = time.perf_counter()
    try:
        final_state = await _run_base_pipeline(question)
    except Exception as e:
        print(f"Pipeline failed    : {type(e).__name__}: {e}")
        return 1
    pipeline_ms = (time.perf_counter() - pipeline_start) * 1000

    generated_sql = final_state.get("generated_sql")
    query_result = final_state.get("query_result")
    analytics = final_state.get("analytics")

    print(f"SQL source         : {getattr(generated_sql, 'provider', '<none>')}")
    print(f"Generated SQL      : {_redact_sql(getattr(generated_sql, 'sql', None))}")
    print(f"Row count          : {getattr(query_result, 'row_count', 0)}")
    print(f"Base pipeline ms   : {pipeline_ms:.1f}")

    if analytics is None:
        print(
            "\nNo analytics were computed for this question (out of scope, "
            "clarification needed, or SQL failure) — nothing to compare."
        )
        return 0

    for mode in ("deterministic", "ollama", "nvidia", "auto"):
        entry = await _run_mode(mode, analytics)
        _print_result(entry)

    print("\nDone. No API keys, raw patient rows, or full prompts were printed above.")
    return 0


if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_QUESTION
    sys.exit(asyncio.run(main(question)))
