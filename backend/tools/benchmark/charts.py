"""PNG chart generation for benchmark results (matplotlib only, headless)."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend; never open a window
import matplotlib.pyplot as plt

from tools.benchmark.metrics import ModelSummary, QuestionRun, rank_models
from tools.benchmark.report import _ACCURACY_CATEGORIES

_BAR_COLOR = "#4878CF"
_FIG_SIZE = (8, 4.5)


def generate_charts(
    runs: list[QuestionRun],
    summaries: list[ModelSummary],
    charts_dir: Path,
) -> list[Path]:
    """Writes every benchmark chart PNG and returns the created paths."""
    charts_dir.mkdir(parents=True, exist_ok=True)
    ranked = rank_models(summaries)
    created: list[Path] = []

    created.append(_bar_chart(
        charts_dir / "avg_latency.png",
        "Average latency per model",
        [s.model for s in ranked],
        [s.avg_latency_ms / 1000 for s in ranked],
        "seconds",
    ))
    created.append(_bar_chart(
        charts_dir / "sql_generation_latency.png",
        "Average SQL generation latency",
        [s.model for s in ranked],
        [s.avg_sql_generation_ms / 1000 for s in ranked],
        "seconds",
    ))
    created.append(_bar_chart(
        charts_dir / "success_rate.png",
        "Success rate",
        [s.model for s in ranked],
        [s.success_rate for s in ranked],
        "%",
        ylim=(0, 100),
    ))
    created.append(_bar_chart(
        charts_dir / "timeout_rate.png",
        "Timeout rate",
        [s.model for s in ranked],
        [s.timeout_rate for s in ranked],
        "%",
        ylim=(0, 100),
    ))
    created.append(_bar_chart(
        charts_dir / "retry_rate.png",
        "Retry rate",
        [s.model for s in ranked],
        [s.retry_rate for s in ranked],
        "%",
        ylim=(0, 100),
    ))
    created.append(_bar_chart(
        charts_dir / "overall_score.png",
        "Overall score",
        [s.model for s in ranked],
        [s.overall_score for s in ranked],
        "score",
        ylim=(0, 1),
    ))
    created.append(_category_accuracy_chart(charts_dir / "category_accuracy.png", ranked))
    created.append(_token_chart(charts_dir / "token_usage.png", ranked))
    created.append(_latency_distribution_chart(charts_dir / "latency_distribution.png", runs))
    return created


def _bar_chart(
    path: Path,
    title: str,
    labels: list[str],
    values: list[float],
    unit: str,
    ylim: tuple[float, float] | None = None,
) -> Path:
    fig, ax = plt.subplots(figsize=_FIG_SIZE)
    bars = ax.bar(labels, values, color=_BAR_COLOR)
    ax.set_title(title)
    ax.set_ylabel(unit)
    if ylim:
        ax.set_ylim(*ylim)
    ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _category_accuracy_chart(path: Path, ranked: list[ModelSummary]) -> Path:
    categories = [category for category, _ in _ACCURACY_CATEGORIES]
    labels = [label for _, label in _ACCURACY_CATEGORIES]
    fig, ax = plt.subplots(figsize=_FIG_SIZE)
    width = 0.8 / max(len(ranked), 1)
    for index, summary in enumerate(ranked):
        values = [summary.category_success.get(category, 0.0) for category in categories]
        positions = [x + index * width for x in range(len(categories))]
        ax.bar(positions, values, width=width, label=summary.model)
    ax.set_xticks([x + 0.4 - width / 2 for x in range(len(categories))])
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylim(0, 100)
    ax.set_ylabel("%")
    ax.set_title("Category accuracy per model")
    ax.legend(fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _token_chart(path: Path, ranked: list[ModelSummary]) -> Path:
    fig, ax = plt.subplots(figsize=_FIG_SIZE)
    positions = range(len(ranked))
    prompt = [s.avg_prompt_tokens for s in ranked]
    completion = [s.avg_completion_tokens for s in ranked]
    ax.bar(positions, prompt, label="prompt", color=_BAR_COLOR)
    ax.bar(positions, completion, bottom=prompt, label="completion", color="#EE854A")
    ax.set_xticks(list(positions))
    ax.set_xticklabels([s.model for s in ranked])
    ax.set_ylabel("avg tokens per question")
    ax.set_title("Token usage per model")
    ax.legend(fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def _latency_distribution_chart(path: Path, runs: list[QuestionRun]) -> Path:
    models = sorted({run.model for run in runs})
    data = [[run.total_ms / 1000 for run in runs if run.model == model] for model in models]
    fig, ax = plt.subplots(figsize=_FIG_SIZE)
    ax.boxplot(data, tick_labels=models)
    ax.set_ylabel("seconds")
    ax.set_title("Total latency distribution per model")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
