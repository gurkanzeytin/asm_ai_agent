"""Safe NVIDIA NIM (OpenAI-compatible) endpoint smoke test.

Sends one minimal, non-sensitive JSON-only request to confirm NVIDIA_API_KEY
and NVIDIA_MODEL are correctly configured. Prints provider, model, latency,
and the parsed result. Never prints the API key or any patient data.

This is a live network call and is NOT run as part of the automated unit
test suite. Run it explicitly, after setting LLM_PROVIDER=nvidia and
NVIDIA_API_KEY in your local .env file:

    python scripts/verify_nvidia_connection.py

Exits 0 on success, non-zero on any failure.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add backend directory to sys.path to resolve 'app' correctly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings  # noqa: E402
from app.llm.exceptions import LLMException  # noqa: E402
from app.llm.nvidia import NvidiaProvider, resolve_nvidia_model_profile  # noqa: E402

_SYSTEM_PROMPT = "You produce valid Microsoft SQL Server query plans. Return JSON only."

# Minimal, non-sensitive per-model probes. Each expects an exact, small JSON
# object back — enough to confirm the endpoint/model pair actually answers,
# without sending any schema, query, or patient-adjacent content.
_MODEL_PROBES: dict[str, str] = {
    "z-ai/glm-5.2": 'Return exactly:\n{"status":"ok","model":"glm-5.2"}',
    "nvidia/nemotron-3-ultra-550b-a55b": (
        'Return exactly:\n{"status":"ok","model":"nemotron-3-ultra"}'
    ),
}
_DEFAULT_PROBE = 'Return exactly:\n{"status":"ok","dialect":"tsql"}'


def _probe_for(model: str) -> str:
    return _MODEL_PROBES.get(model, _DEFAULT_PROBE)


async def main() -> int:
    model = settings.NVIDIA_MODEL
    profile = resolve_nvidia_model_profile(model)
    user_prompt = _probe_for(model)

    print("===== NVIDIA CONNECTION VERIFICATION =====")
    print("Provider            : nvidia")
    print(f"Model               : {model}")
    print(f"Base URL            : {settings.NVIDIA_BASE_URL}")
    print(f"Timeout (s)         : {settings.NVIDIA_TIMEOUT_SECONDS}")
    print(f"Max retries         : {settings.NVIDIA_MAX_RETRIES}")
    print(f"Supports thinking   : {profile.supports_thinking}")
    print(f"Thinking key        : {profile.thinking_key if profile.supports_thinking else 'n/a'}")
    print(f"Default temperature : {profile.default_temperature}")
    print(f"Default top_p       : {profile.default_top_p}")
    print(f"Recommended max_tok : {profile.recommended_max_tokens}")
    print(f"API key configured  : {'yes' if settings.NVIDIA_API_KEY.get_secret_value() else 'no'}")

    if not settings.NVIDIA_API_KEY.get_secret_value():
        print("Connection test     : FAILED")
        print("Error               : NVIDIA_API_KEY is not set. Put it only in your .env file.")
        return 1

    provider = NvidiaProvider()
    start = time.perf_counter()
    try:
        response = await provider.generate(
            user_prompt,
            think=False,
            options={"system": _SYSTEM_PROMPT, "max_tokens": 64, "stream": False},
        )
    except LLMException as e:
        print("Connection test     : FAILED")
        print(f"Error               : {type(e).__name__}: {e}")
        return 1
    except Exception as e:
        print("Connection test     : FAILED (unexpected error)")
        print(f"Error               : {type(e).__name__}: {e}")
        return 1
    finally:
        await provider.close()

    elapsed_ms = (time.perf_counter() - start) * 1000

    print("Connection test     : OK")
    print("Provider            : nvidia")
    print(f"Model               : {response.model}")
    print(f"Latency (ms)        : {elapsed_ms:.1f}")
    print(f"Finish reason       : {response.finish_reason}")
    print(f"Prompt tokens       : {response.prompt_tokens}")
    print(f"Completion tokens   : {response.completion_tokens}")
    print(f"Raw result          : {response.content}")

    try:
        parsed = json.loads(response.content)
        print(f"Parsed JSON         : {parsed}")
    except json.JSONDecodeError:
        print("Parsed JSON         : FAILED (response was not valid JSON)")
        return 1

    print("Verification completed successfully. No API key or patient data was printed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
