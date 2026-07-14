"""Benchmark output generation: benchmark_summary.md, benchmark.csv, benchmark.json."""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from tools.benchmark.metrics import (
    ModelSummary,
    QuestionRun,
    Reason,
    rank_models,
    summarize_model,
)

_CSV_FIELDS = [
    "model", "question_id", "category", "question", "repeat_index",
    "outcome", "reason", "generated_sql", "execution_success", "rows_returned",
    "analytics_generated", "insight_generated", "report_generated",
    "total_ms", "sql_generation_ms", "analytics_ms", "insight_ms", "report_ms",
    "llm_calls", "llm_timeouts", "retry_count",
    "prompt_tokens", "completion_tokens", "finish_reasons", "errors", "exception",
]

_FAILURE_COLUMNS = [
    (Reason.TIMEOUT, "Timeout"),
    (Reason.INVALID_SQL, "Invalid SQL"),
    (Reason.WRONG_ENTITY, "Wrong Entity"),
    (Reason.WRONG_JOIN, "Wrong Join"),
    (Reason.PIPELINE_FAILURE, "Pipeline Error"),
    (Reason.NO_RESULTS, "Empty Result"),
    (Reason.SQL_GENERATION_FAILED, "SQL Gen Failed"),
]

_ACCURACY_CATEGORIES = [
    ("listing", "Listing"),
    ("count", "Count"),
    ("trend", "Trend"),
    ("comparison", "Comparison"),
    ("analytics", "Analytics"),
    ("ranking", "Ranking"),
    ("date_filtering", "Date"),
]

_CHART_FILES = [
    ("avg_latency.png", "Average latency per model"),
    ("sql_generation_latency.png", "SQL generation latency"),
    ("success_rate.png", "Success rate"),
    ("timeout_rate.png", "Timeout rate"),
    ("overall_score.png", "Overall score"),
    ("category_accuracy.png", "Category accuracy"),
    ("token_usage.png", "Token usage"),
    ("latency_distribution.png", "Latency distribution"),
]


def summarize_all(runs: list[QuestionRun]) -> list[ModelSummary]:
    models = sorted({run.model for run in runs})
    return rank_models([
        summarize_model(model, [r for r in runs if r.model == model]) for model in models
    ])


def write_json(runs: list[QuestionRun], summaries: list[ModelSummary], path: Path) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summaries": [summary.to_dict() for summary in summaries],
        "runs": [run.to_dict() for run in runs],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(runs: list[QuestionRun], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for run in runs:
            row = run.to_dict()
            row["finish_reasons"] = "|".join(run.finish_reasons)
            row["errors"] = "|".join(run.errors)
            writer.writerow(row)


def build_markdown(
    summaries: list[ModelSummary],
    skipped_models: list[str],
    total_duration_s: float,
    charts_relative_dir: str = "../charts",
) -> str:
    """Renders benchmark_summary.md content (deterministic, no LLM)."""
    ranked = rank_models(summaries)
    lines: list[str] = []
    lines.append("# Benchmark Summary Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append(f"Total duration: {total_duration_s:.0f}s  ")
    if skipped_models:
        lines.append(f"Skipped models (not installed): {', '.join(skipped_models)}  ")
    lines.append("")

    # ── Overall ranking ──
    lines.append("## Overall Ranking")
    lines.append("")
    lines.append(
        "| Rank | Model | Success Rate | Avg Time | P95 | Avg SQL Time | Timeout | Retries | Overall Score |"
    )
    lines.append("|------|-------|-------------:|---------:|----:|-------------:|--------:|--------:|--------------:|")
    for index, summary in enumerate(ranked, 1):
        lines.append(
            f"| {index} | {summary.model} | {summary.success_rate}% "
            f"| {_fmt_s(summary.avg_latency_ms)} | {_fmt_s(summary.p95_latency_ms)} "
            f"| {_fmt_s(summary.avg_sql_generation_ms)} | {summary.timeout_rate}% "
            f"| {summary.retry_rate}% | {summary.overall_score:.3f} |"
        )
    lines.append("")

    # ── Performance breakdown ──
    lines.append("## Performance Breakdown")
    lines.append("")
    lines.append("| Model | Avg Workflow | SQL Gen | Analytics | Insight | Report | Total LLM Time |")
    lines.append("|-------|-------------:|--------:|----------:|--------:|-------:|---------------:|")
    for summary in ranked:
        lines.append(
            f"| {summary.model} | {_fmt_s(summary.avg_latency_ms)} | {_fmt_s(summary.avg_sql_generation_ms)} "
            f"| {summary.avg_analytics_ms:.1f} ms | {_fmt_s(summary.avg_insight_ms)} "
            f"| {_fmt_s(summary.avg_report_ms)} | {_fmt_s(summary.avg_total_llm_ms)} |"
        )
    lines.append("")

    # ── Accuracy breakdown ──
    lines.append("## Accuracy Breakdown")
    lines.append("")
    header = "| Model | " + " | ".join(label for _, label in _ACCURACY_CATEGORIES) + " | Overall |"
    lines.append(header)
    lines.append("|-------|" + "----:|" * (len(_ACCURACY_CATEGORIES) + 1))
    for summary in ranked:
        cells = [
            _fmt_pct(summary.category_success.get(category))
            for category, _ in _ACCURACY_CATEGORIES
        ]
        lines.append(
            f"| {summary.model} | " + " | ".join(cells) + f" | {summary.success_rate}% |"
        )
    lines.append("")

    # ── Failure analysis ──
    lines.append("## Failure Analysis")
    lines.append("")
    lines.append("| Model | " + " | ".join(label for _, label in _FAILURE_COLUMNS) + " |")
    lines.append("|-------|" + "----:|" * len(_FAILURE_COLUMNS))
    for summary in ranked:
        cells = [str(summary.failure_reasons.get(reason.value, 0)) for reason, _ in _FAILURE_COLUMNS]
        lines.append(f"| {summary.model} | " + " | ".join(cells) + " |")
    lines.append("")

    # ── Resource usage ──
    lines.append("## Resource Usage")
    lines.append("")
    lines.append("| Model | Avg Prompt Tokens | Avg Completion Tokens | Avg Total Tokens |")
    lines.append("|-------|------------------:|----------------------:|-----------------:|")
    for summary in ranked:
        lines.append(
            f"| {summary.model} | {summary.avg_prompt_tokens:.0f} "
            f"| {summary.avg_completion_tokens:.0f} | {summary.avg_total_tokens:.0f} |"
        )
    lines.append("")

    # ── Recommendation ──
    lines.append("## Recommendation")
    lines.append("")
    lines.extend(build_recommendation(ranked))
    lines.append("")

    # ── Charts ──
    lines.append("## Charts")
    lines.append("")
    for filename, title in _CHART_FILES:
        lines.append(f"![{title}]({charts_relative_dir}/{filename})")
        lines.append("")

    return "\n".join(lines)


def build_recommendation(ranked: list[ModelSummary]) -> list[str]:
    """Deterministic recommendation block derived only from measured metrics."""
    if not ranked:
        return ["No successful benchmark runs — no recommendation available."]
    fastest = min(ranked, key=lambda s: s.avg_latency_ms)
    most_accurate = max(ranked, key=lambda s: s.success_rate)
    best = ranked[0]
    reason = (
        f"'{best.model}' has the highest overall score ({best.overall_score:.3f}) "
        f"combining a {best.success_rate}% success rate with an average total "
        f"latency of {_fmt_s(best.avg_latency_ms)} "
        f"(P95 {_fmt_s(best.p95_latency_ms)}, timeout rate {best.timeout_rate}%)."
    )
    return [
        f"**Fastest Model:** {fastest.model} ({_fmt_s(fastest.avg_latency_ms)} avg)",
        "",
        f"**Most Accurate Model:** {most_accurate.model} ({most_accurate.success_rate}% success)",
        "",
        f"**Best Overall Model:** {best.model} (score {best.overall_score:.3f})",
        "",
        f"**Recommended Production Model:** {best.model}",
        "",
        f"**Reason:** {reason}",
    ]


def write_markdown(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fmt_s(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.1f} s"
    return f"{ms:.0f} ms"


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value}%"
