"""Benchmark configuration: candidate models, paths, scoring weights.

Models are plain strings — adding a new Ollama model requires no code change:
pass ``--model <name>`` or extend DEFAULT_MODELS / the BENCHMARK_MODELS env var.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repository layout (this file lives in backend/tools/benchmark/).
BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
DATASET_PATH = REPO_ROOT / "benchmark" / "questions.json"
RESULTS_DIR = REPO_ROOT / "benchmark" / "results"
CHARTS_DIR = REPO_ROOT / "benchmark" / "charts"

# Initial candidate set (PERF-001). Extend freely; unavailable models are skipped
# with a warning instead of failing the run.
DEFAULT_MODELS: list[str] = [
    "qwen3:8b",
    "qwen2.5:3b",
    "qwen2.5:7b",
    "gemma3",
    "llama3.2",
    "mistral",
]

# Overall score = success-weight * success_rate + speed-weight * speed_score.
# speed_score linearly maps average total latency: <= FAST_MS -> 1.0, >= SLOW_MS -> 0.0.
SCORE_SUCCESS_WEIGHT = 0.7
SCORE_SPEED_WEIGHT = 0.3
SPEED_FAST_MS = 5_000.0
SPEED_SLOW_MS = 60_000.0

# A single question run is aborted after this many seconds (pipeline hang guard).
QUESTION_TIMEOUT_S = 180.0


def models_from_env() -> list[str]:
    """Optional override: BENCHMARK_MODELS="qwen3:8b,mistral"."""
    raw = os.environ.get("BENCHMARK_MODELS", "")
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    return parsed or list(DEFAULT_MODELS)


@dataclass
class BenchmarkConfig:
    models: list[str] = field(default_factory=models_from_env)
    dataset_path: Path = DATASET_PATH
    results_dir: Path = RESULTS_DIR
    charts_dir: Path = CHARTS_DIR
    repeat: int = 1
    limit: int | None = None
    categories: list[str] | None = None
    question_timeout_s: float = QUESTION_TIMEOUT_S
