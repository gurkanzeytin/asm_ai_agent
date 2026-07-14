"""PERF-001 — Automated LLM benchmark CLI.

Runs the benchmark dataset (benchmark/questions.json) against one or more
Ollama models through the full production workflow and generates:

    benchmark/results/benchmark_summary.md
    benchmark/results/benchmark.csv
    benchmark/results/benchmark.json
    benchmark/charts/*.png

Usage:
    python benchmark.py --model qwen3:8b
    python benchmark.py --all-models --repeat 3
    python benchmark.py --model qwen3:8b --limit 10 --output benchmark/results

The tool never modifies the production application; it wires its own pipeline
per model via dependency injection (backend/tools/benchmark/).
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPO_ROOT / "backend"

# The production app resolves its SQLite path relative to backend/.
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(level=logging.WARNING)
logging.getLogger("tools.benchmark").setLevel(logging.INFO)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASM AI Agent SQL-generation LLM benchmark")
    parser.add_argument("--model", action="append", default=None,
                        help="Model to benchmark (repeatable). Example: --model qwen3:8b")
    parser.add_argument("--all-models", action="store_true",
                        help="Benchmark every model in the default candidate list")
    parser.add_argument("--output", default=None,
                        help="Results directory (default: benchmark/results)")
    parser.add_argument("--repeat", type=int, default=1, help="Repetitions per question")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of questions")
    parser.add_argument("--categories", default=None,
                        help="Comma-separated category filter (e.g. trend,count)")
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> int:
    from tools.benchmark.config import DEFAULT_MODELS, BenchmarkConfig
    from tools.benchmark.charts import generate_charts
    from tools.benchmark.report import (
        build_markdown, summarize_all, write_csv, write_json, write_markdown,
    )
    from tools.benchmark.runner import run_benchmark

    if args.model:
        models = args.model
    elif args.all_models:
        models = list(DEFAULT_MODELS)
    else:
        models = list(DEFAULT_MODELS)
        print("No --model given; defaulting to --all-models candidate list.")

    config = BenchmarkConfig(
        models=models,
        repeat=max(1, args.repeat),
        limit=args.limit,
        categories=args.categories.split(",") if args.categories else None,
    )
    if args.output:
        config.results_dir = (REPO_ROOT / args.output).resolve() \
            if not Path(args.output).is_absolute() else Path(args.output)

    started = time.perf_counter()
    runs, skipped = await run_benchmark(config)
    duration_s = time.perf_counter() - started

    summaries = summarize_all(runs)
    results_dir = config.results_dir
    write_json(runs, summaries, results_dir / "benchmark.json")
    write_csv(runs, results_dir / "benchmark.csv")
    charts = generate_charts(runs, summaries, config.charts_dir)
    markdown = build_markdown(summaries, skipped, duration_s)
    write_markdown(markdown, results_dir / "benchmark_summary.md")

    fastest = min(summaries, key=lambda s: s.avg_latency_ms)
    most_accurate = max(summaries, key=lambda s: s.success_rate)
    print("\n================ BENCHMARK SUMMARY ================")
    print(f"Total duration : {duration_s:.0f}s ({len(runs)} runs)")
    print(f"Fastest model  : {fastest.model} ({fastest.avg_latency_ms / 1000:.1f}s avg)")
    print(f"Highest accuracy: {most_accurate.model} ({most_accurate.success_rate}%)")
    print(f"Best overall   : {summaries[0].model} (score {summaries[0].overall_score:.3f})")
    print(f"Results        : {results_dir}")
    print(f"Charts         : {len(charts)} PNGs in {config.charts_dir}")
    print("===================================================")
    return 0


def main() -> int:
    return asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
