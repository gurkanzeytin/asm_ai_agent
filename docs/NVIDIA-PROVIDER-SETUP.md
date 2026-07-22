# NVIDIA NIM Provider Setup

The agent supports NVIDIA's OpenAI-compatible endpoint
(`https://integrate.api.nvidia.com/v1`) as an alternate `LLM_PROVIDER`, alongside
the default local Ollama/Qwen3 8B provider. Selection is a static configuration
choice (`ollama` or `nvidia`) — there is no automatic hybrid routing yet.

`NvidiaProvider` is a single provider class that talks to one endpoint with one
`AsyncOpenAI` client. Multiple NVIDIA-hosted models are supported through that
same provider — there is no separate provider class per model. Which model is
active is controlled entirely by `NVIDIA_MODEL`:

```
NVIDIA_MODEL=deepseek-ai/deepseek-v4-pro   # default
NVIDIA_MODEL=z-ai/glm-5.2
```

Both model families use **the same** `NVIDIA_API_KEY` and `NVIDIA_BASE_URL` —
there is no `GLM_API_KEY` or `GLM_BASE_URL`. Only the request payload shape
differs per model, and that difference is resolved automatically from the
`NVIDIA_MODEL` value via a small internal profile table
(`app.llm.nvidia.resolve_nvidia_model_profile`); no extra setting is needed to
select it.

### Model-specific request differences

| | DeepSeek (`deepseek-ai/deepseek-v4-pro`) | GLM (`z-ai/glm-5.2`) |
|---|---|---|
| `temperature` default | `NVIDIA_TEMPERATURE` (0.1) | `1.0` |
| `top_p` default | `NVIDIA_TOP_P` (0.95) | `1.0` |
| `max_tokens` default | `NVIDIA_MAX_TOKENS` | `NVIDIA_MAX_TOKENS` |
| `extra_body` | `{"chat_template_kwargs": {"thinking": <bool>}}` | not sent |

GLM does **not** receive DeepSeek's `chat_template_kwargs.thinking` extra_body.
That field is a DeepSeek-specific request extension; it is only sent to models
whose profile explicitly declares `supports_thinking=True`. Do not add it to
GLM's profile unless NVIDIA's official GLM documentation confirms the field is
accepted — sending unsupported fields to a strict endpoint can fail the
request outright rather than being silently ignored.

Any model id not listed in the profile table falls back to DeepSeek's request
shape, so adding an experimental model to `NVIDIA_MODEL` never changes
behavior for the models already in production use.

## 1. Generate an NVIDIA API key

Create a key at https://build.nvidia.com (NVIDIA account required).

## 2. Put the key only in `.env`

```
NVIDIA_API_KEY=nvapi-...
```

Never commit this value or paste it into code, prompts, or tickets. `.env` is
already listed in `.gitignore`.

## 3. Select the NVIDIA provider

```
LLM_PROVIDER=nvidia
```

Optional overrides (defaults shown):

```
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_MODEL=deepseek-ai/deepseek-v4-pro
NVIDIA_TIMEOUT_SECONDS=90
NVIDIA_MAX_RETRIES=1
NVIDIA_MAX_TOKENS=2048
NVIDIA_TEMPERATURE=0.1
NVIDIA_TOP_P=0.95
NVIDIA_THINKING=false
```

`NVIDIA_API_KEY` is only required when `LLM_PROVIDER=nvidia`; the application
fails fast at startup with a clear configuration error if it is missing.

## 4. Run the smoke test

```
cd backend
python scripts/verify_nvidia_connection.py
```

Tests whichever model is currently set in `NVIDIA_MODEL` — set it to
`deepseek-ai/deepseek-v4-pro` or `z-ai/glm-5.2` before running to test that
model specifically. Sends one minimal, non-sensitive, non-streaming JSON-only
request and prints the selected provider/model, latency, finish reason, token
usage, and the parsed result. Never prints the API key. Exits non-zero on
failure. This is a live network call and is not part of the automated unit
test suite.

## 4a. Choosing a production default

**Do not pick a production default model from vibes or a single manual run.**
`NVIDIA_TEMPERATURE`/`NVIDIA_TOP_P` are tuned for DeepSeek's SQL-generation
behavior; GLM's officially documented defaults (`temperature=1`, `top_p=1`)
are deliberately different. Before changing the default away from
`deepseek-ai/deepseek-v4-pro`, measure `qwen3:8b` (local baseline),
`deepseek-ai/deepseek-v4-pro`, and `z-ai/glm-5.2` head-to-head against the
same question set and compare success rate, latency (avg + P95), timeout
rate, and token usage — not a handful of manual smoke-test prompts. The
project's benchmark harness (`backend/tools/benchmark/`) currently wires only
`OllamaProvider` (`ModelPipeline.build_pipeline`); running an NVIDIA model
through it requires injecting `NvidiaProvider` there first — a separate,
explicit change, not implied by this provider integration.

## 5. Switch back to Ollama

```
LLM_PROVIDER=ollama
```

No other setting needs to change; `OLLAMA_*` configuration is untouched by the
NVIDIA integration.

## 6. Security warning

**Never send raw patient rows to NVIDIA or any external provider.** Every
NVIDIA-bound request is screened by `backend/app/llm/remote_policy.py`, which
rejects any prompt referencing patient-level or direct/indirect personal
identifiers (`HastaAdi`, `HastaSoyadi`, `HastaId`, `HastaId2`, `DogumTarihi`,
`CinsiyetId`, `Uyruk`, `RandevuyuVeren`, and the already-removed
`TCKimlikNo`/`PasaportNo`/`HastaGSM`) with a `RemoteDataPolicyViolation`. Remote
requests should only ever carry schema metadata, query plans, SQL generation
instructions, and anonymized aggregate results (grouped counts, ratios,
trends, summaries) — never row-level identities.
