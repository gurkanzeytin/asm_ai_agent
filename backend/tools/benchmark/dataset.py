"""Benchmark dataset loading and validation."""

import json
from dataclasses import dataclass
from pathlib import Path


class DatasetError(Exception):
    """Raised when the benchmark dataset is missing or malformed."""


@dataclass(frozen=True)
class BenchmarkQuestion:
    id: int
    category: str
    question: str


def load_dataset(
    path: Path,
    categories: list[str] | None = None,
    limit: int | None = None,
) -> list[BenchmarkQuestion]:
    """Loads and validates benchmark/questions.json.

    Args:
        path: Dataset file path.
        categories: Optional category filter (exact match).
        limit: Optional cap on the number of questions (applied after filtering).
    """
    if not path.exists():
        raise DatasetError(f"Benchmark dataset not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DatasetError(f"Benchmark dataset is not valid JSON: {e}") from e

    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise DatasetError("Benchmark dataset must contain a non-empty 'questions' list.")

    questions: list[BenchmarkQuestion] = []
    seen_ids: set[int] = set()
    for entry in raw_questions:
        if not isinstance(entry, dict):
            raise DatasetError(f"Question entry is not an object: {entry!r}")
        missing = {"id", "category", "question"} - set(entry)
        if missing:
            raise DatasetError(f"Question entry missing fields {missing}: {entry!r}")
        question_id = int(entry["id"])
        if question_id in seen_ids:
            raise DatasetError(f"Duplicate question id: {question_id}")
        seen_ids.add(question_id)
        text = str(entry["question"]).strip()
        if not text:
            raise DatasetError(f"Question {question_id} has empty text.")
        questions.append(
            BenchmarkQuestion(id=question_id, category=str(entry["category"]), question=text)
        )

    if categories:
        wanted = set(categories)
        questions = [q for q in questions if q.category in wanted]
        if not questions:
            raise DatasetError(f"No questions matched categories: {sorted(wanted)}")
    if limit is not None:
        questions = questions[:limit]
    return questions


def dataset_categories(questions: list[BenchmarkQuestion]) -> list[str]:
    """Returns categories in first-appearance order."""
    ordered: list[str] = []
    for question in questions:
        if question.category not in ordered:
            ordered.append(question.category)
    return ordered
