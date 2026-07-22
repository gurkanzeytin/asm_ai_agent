"""Accessors over the central view semantic metadata (resources/view_semantics.json).

Single source of truth for mapping user language (Turkish business concepts) to the
real columns of the allowed reporting view. Consumed by the schema inspector
(column descriptions), the query planner (column/date/measure resolution), and
schema grounding (concept mapping lines for the LLM). Extend the JSON — not the
consumers — when new concepts are needed.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_VIEW_SEMANTICS_PATH = Path(__file__).resolve().parent.parent / "resources" / "view_semantics.json"

# Diacritic fold table matching the analyzer/extractor normalization.
_FOLD_TABLE = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ğ": "g",
        "Ğ": "g",
        "ş": "s",
        "Ş": "s",
        "ç": "c",
        "Ç": "c",
        "ö": "o",
        "Ö": "o",
        "ü": "u",
        "Ü": "u",
    }
)


def fold(text: str) -> str:
    """Diacritic-folds and lowercases Turkish text for term matching."""
    return text.translate(_FOLD_TABLE).lower()


@lru_cache(maxsize=1)
def load_view_semantics() -> dict:
    """Loads curated semantic metadata for known views from resources.

    Missing or unreadable files degrade to an empty mapping with a logged error
    (semantic grounding is enrichment, not a hard requirement).
    """
    try:
        return json.loads(_VIEW_SEMANTICS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Could not load view semantics resource '{_VIEW_SEMANTICS_PATH.name}': {e}")
        return {}


def get_view_entry(view_name: str | None = None) -> dict:
    """Returns the semantic entry for a view (default: the single configured view)."""
    semantics = load_view_semantics()
    if not semantics:
        return {}
    if view_name:
        entry = semantics.get(view_name) or semantics.get(view_name.split(".")[-1])
        if entry:
            return entry
        lowered = view_name.lower()
        for key, value in semantics.items():
            if key.lower() == lowered or key.lower().endswith(f".{lowered}"):
                return value
        return {}
    # Single-view deployments: the first (only) entry is the active view.
    return next(iter(semantics.values()), {})


def concept_column(entity_type: str, view_name: str | None = None) -> str | None:
    """Resolves a semantic entity/concept name to its preferred view column."""
    concepts = get_view_entry(view_name).get("concepts", {})
    concept = concepts.get(entity_type, {})
    return concept.get("column")


def concept_for_terms(folded_question: str, view_name: str | None = None) -> dict[str, str]:
    """Returns {concept_name: column} for every concept whose terms appear in the question."""
    matches: dict[str, str] = {}
    for name, spec in get_view_entry(view_name).get("concepts", {}).items():
        column = spec.get("column")
        if not column:
            continue
        if any(fold(term) in folded_question for term in spec.get("terms", [])):
            matches[name] = column
    return matches


def resolve_date_column(folded_question: str, view_name: str | None = None) -> str | None:
    """Chooses the date column implied by the question wording.

    Rule order in the metadata matters: more specific wording (protokol, oluşturulan)
    is listed before the default appointment-start column.
    """
    date_semantics = get_view_entry(view_name).get("date_semantics", {})
    for rule in date_semantics.get("rules", []):
        if any(fold(term) in folded_question for term in rule.get("terms", [])):
            return rule.get("column")
    return date_semantics.get("default_column")


def resolve_measure(folded_question: str, view_name: str | None = None) -> str | None:
    """Resolves counting wording to the correct aggregate expression."""
    for spec in get_view_entry(view_name).get("measures", {}).values():
        if any(fold(term) in folded_question for term in spec.get("terms", [])):
            return spec.get("expression")
    return None


def resolve_status_filter(folded_question: str, view_name: str | None = None) -> str | None:
    """Maps status wording (gerçekleşen, iptal, ...) to a RandevuDurumu filter value."""
    status_filters = get_view_entry(view_name).get("status_filters", {})
    concepts = get_view_entry(view_name).get("concepts", {})
    status_column = concepts.get("AppointmentStatus", {}).get("column", "RandevuDurumu")
    for term, stored_value in status_filters.items():
        if fold(term) in folded_question:
            return f"{status_column} = '{stored_value}'"
    return None


def concept_mapping_lines(view_name: str | None = None) -> list[str]:
    """Compact user-language → column lines for the LLM schema grounding block."""
    entry = get_view_entry(view_name)
    lines: list[str] = []
    for spec in entry.get("concepts", {}).values():
        terms = spec.get("terms", [])
        column = spec.get("column")
        if terms and column:
            lines.append(f"    - {'/'.join(terms[:3])} -> {column}")
    date_semantics = entry.get("date_semantics", {})
    default_column = date_semantics.get("default_column")
    if default_column:
        lines.append(f"    - randevu tarihi (varsayilan) -> {default_column}")
    for rule in date_semantics.get("rules", []):
        terms = rule.get("terms", [])
        if terms and rule.get("column"):
            lines.append(f"    - {terms[0]} -> {rule['column']}")
    for spec in entry.get("measures", {}).values():
        terms = spec.get("terms", [])
        if terms and spec.get("expression"):
            lines.append(f"    - {terms[0]} -> {spec['expression']}")
    return lines
