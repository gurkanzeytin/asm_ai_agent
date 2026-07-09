"""
verify_ollama.py — Minimal OllamaProvider connectivity verification.

Calls OllamaProvider.generate("Say Hello") directly.
No LangGraph, no PromptService, no SQL, no database.

Usage (from workspace root):
    python verify_ollama.py
"""
import asyncio
import logging
import sys
import time

# Add backend to sys.path
sys.path.insert(0, "backend")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("verify_ollama")


async def main() -> None:
    from app.core.config import settings
    from app.llm.ollama import OllamaProvider

    logger.info("=== Ollama Provider Verification ===")
    logger.info(f"OLLAMA_BASE_URL  : {settings.OLLAMA_BASE_URL}")
    logger.info(f"OLLAMA_MODEL     : {settings.OLLAMA_MODEL}")
    logger.info(f"OLLAMA_TIMEOUT   : {settings.OLLAMA_TIMEOUT}")
    logger.info(f"LLM_RETRY_COUNT  : {settings.LLM_RETRY_COUNT}")

    provider = OllamaProvider()
    logger.info(f"Provider base_url : {provider.base_url}")
    logger.info(f"Provider model    : {provider.model}")
    logger.info(f"Provider timeout  : {provider.timeout}")
    logger.info(f"Provider retries  : {provider.retry_count}")
    logger.info(f"httpx client timeout: {provider._client.timeout}")

    # Health check first
    logger.info("--- Health check (GET /api/tags) ---")
    healthy = await provider.health_check()
    logger.info(f"Health check result: {'OK' if healthy else 'FAILED'}")

    if not healthy:
        logger.error("Ollama is unreachable. Check that Ollama is running.")
        return

    # Minimal generate call
    logger.info("--- Calling provider.generate('Say Hello') ---")
    t0 = time.perf_counter()
    try:
        response = await provider.generate("Say Hello")
        elapsed = time.perf_counter() - t0
        logger.info(f"SUCCESS in {elapsed:.2f}s")
        logger.info(f"Response content : {response.content[:200]!r}")
        logger.info(f"Model            : {response.model}")
        logger.info(f"Latency (ms)     : {response.latency_ms:.0f}")
        logger.info(f"Prompt tokens    : {response.prompt_tokens}")
        logger.info(f"Completion tokens: {response.completion_tokens}")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.error(f"FAILED after {elapsed:.2f}s")
        logger.error(f"Exception type   : {type(e).__name__}")
        logger.error(f"Exception message: {e}")
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
