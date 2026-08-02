"""Actionable follow-up questions for controlled workflow outcomes."""

from __future__ import annotations

from app.application_models.outcome import AgentOutcome
from app.application_models.schema_capability import SchemaCapabilityAnswer
from app.semantics import catalog
from app.semantics.question_examples import column_question_examples

_GUIDANCE_OUTCOMES = {
    AgentOutcome.OUT_OF_SCOPE.value,
    AgentOutcome.NO_RESULT_GUIDANCE.value,
    AgentOutcome.SAFE_ERROR.value,
    AgentOutcome.REWRITE_AND_RETRY.value,
}
_GUIDANCE_COLUMNS = ("SubeAdi", "RandevuSuresi", "Uyruk", "CreatedDate")


def _catalog_guidance_questions() -> list[str]:
    by_name = {spec.column: spec for spec in catalog.load_column_catalog().columns}
    return [
        column_question_examples(by_name[column_name])[0]
        for column_name in _GUIDANCE_COLUMNS
        if column_name in by_name
    ]


def build_suggested_questions(
    *,
    outcome: str | None,
    ambiguity_options: list[str] | None = None,
    capability: SchemaCapabilityAnswer | None = None,
    limit: int = 4,
) -> list[str]:
    """Build bounded, deterministic suggestions without inventing data values."""
    if outcome == AgentOutcome.ASK_CLARIFICATION.value:
        candidates = [
            option
            for option in (ambiguity_options or [])
            if option and "sorumu değiştireceğim" not in option.casefold()
        ]
    elif outcome == AgentOutcome.RETURN_HELP.value and capability is not None:
        candidates = capability.example_questions
    elif outcome in _GUIDANCE_OUTCOMES:
        candidates = _catalog_guidance_questions()
    else:
        candidates = []

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(candidate.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
        if len(unique) >= limit:
            break
    return unique
