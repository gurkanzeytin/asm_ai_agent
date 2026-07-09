"""
benchmark.py — Benchmark comparison between Ollama and Gemini providers.

Runs the analytical question:
    "En çok randevusu olan doktor kim?"

Compares:
- SQL generation latency
- report latency
- completion tokens
- finish reason
- raw SQL
- parsed SQL
- final SQL executed
"""
import asyncio
import logging
import os
import sys
import time
from typing import Any

# Change working directory to backend so database path resolves correctly
if os.path.exists("backend"):
    os.chdir("backend")
sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("benchmark")


async def run_benchmark_for_provider(provider_type: str) -> dict[str, Any]:
    from app.core.config import settings
    from app.llm.provider import LLMFactory
    from app.bootstrap import AppContainer

    # Temporarily set the active provider
    settings.LLM_PROVIDER = provider_type
    LLMFactory._instances.clear()

    # Verify key if gemini
    if provider_type == "gemini" and not settings.GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY is not configured in backend/.env"}

    logger.info(f"\n================ Running Benchmark for: {provider_type.upper()} ================")

    # Initialize a new container to resolve dependencies with the updated LLM provider
    container = AppContainer()
    
    # Check health/connectivity first
    is_healthy = await container.llm_provider.health_check()
    if not is_healthy:
        return {"error": f"Provider {provider_type} is not healthy or unreachable."}

    # Benchmark timings
    t0 = time.perf_counter()
    # Invoke reporting service directly
    result = await container.reporting_service.run_workflow("En çok randevusu olan doktor kim?")
    total_elapsed = time.perf_counter() - t0

    # Extract metrics from WorkflowResult
    if result.errors:
        return {"error": f"Workflow failed to complete. Errors: {result.errors}"}

    # Find the execution nodes for metrics:
    # Since we mapped them, generated_sql and generated_report are returned in result.
    generated_sql_sql = result.generated_sql
    # Wait, in WorkflowResult, generated_sql is just a string, and generated_report is a GeneratedReport DTO.
    # But wait, how do we get the latency/tokens for SQL generation?
    # Let's inspect ReportingService timings mapping.
    # In compile_report, the WorkflowResult.metrics holds:
    # analyze_intent_ms, retrieve_context_ms, generate_sql_ms, validate_sql_ms, execute_sql_ms, generate_report_ms, total_ms, llm_total_ms
    metrics = result.metrics

    return {
        "provider": provider_type,
        "total_latency_s": total_elapsed,
        "sql_latency_ms": metrics.generate_sql_ms,
        "report_latency_ms": metrics.generate_report_ms,
        "completion_tokens": result.generated_report.completion_tokens if result.generated_report else None,
        "finish_reason": getattr(result.generated_report, "finish_reason", "N/A"),
        "final_sql": result.generated_sql,
        "report": result.generated_report.markdown if result.generated_report else None,
    }


async def main() -> None:
    results = {}
    
    # 1. Run Ollama
    try:
        results["ollama"] = await run_benchmark_for_provider("ollama")
    except Exception as e:
        results["ollama"] = {"error": f"Failed with exception: {e}"}

    # 2. Run Gemini
    try:
        results["gemini"] = await run_benchmark_for_provider("gemini")
    except Exception as e:
        results["gemini"] = {"error": f"Failed with exception: {e}"}

    # Print comparison summary table
    print("\n\n" + "=" * 80)
    print("                    BENCHMARK COMPARISON SUMMARY")
    print("=" * 80)
    print(f"{'Metric':<25} | {'Ollama':<25} | {'Gemini':<25}")
    print("-" * 80)

    def display_metric(name: str, key: str) -> None:
        val_o = results["ollama"].get(key, "N/A") if "error" not in results["ollama"] else "ERROR"
        val_g = results["gemini"].get(key, "N/A") if "error" not in results["gemini"] else "ERROR"
        
        # If there's an error, print the error details
        if key == "error":
            val_o = results["ollama"].get("error", "None")
            val_g = results["gemini"].get("error", "None")
            
        print(f"{name:<25} | {str(val_o):<25} | {str(val_g):<25}")

    display_metric("Errors / Status", "error")
    display_metric("Total Latency (s)", "total_latency_s")
    display_metric("SQL Latency (ms)", "sql_latency_ms")
    display_metric("Report Latency (ms)", "report_latency_ms")
    display_metric("Completion Tokens", "completion_tokens")
    display_metric("Finish Reason", "finish_reason")
    display_metric("Final SQL Executed", "final_sql")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
