"""Guards data sent to external (non-local) LLM providers.

Local providers (Ollama) run on infrastructure the organization controls, so no
guard applies to them. Remote providers (NVIDIA today, any future hosted API)
must never receive patient-level or direct/indirect personal identifiers —
only schema metadata, query plans, SQL generation instructions, and anonymized
aggregate results (grouped counts, ratios, trends, summaries).

This module is intentionally generic: it is not specific to any one provider
or any one prompt template, so the same guard applies to every remote-bound
request regardless of which node or service constructed the prompt.
"""

import re

from app.shared.exceptions import AppBaseException

# Direct/indirect patient identifiers that must never leave the organization's
# infrastructure. Matched case-insensitively as whole identifiers so that a
# prompt merely mentioning the *column name* while describing schema metadata
# (e.g. "the view has a HastaAdi column") is still rejected — the safe way to
# reference such a column in a remote-bound prompt is to omit it entirely.
PROHIBITED_PATIENT_FIELDS: frozenset[str] = frozenset(
    {
        "HastaAdi",
        "HastaSoyadi",
        "HastaId",
        "HastaId2",
        "DogumTarihi",
        "CinsiyetId",
        "Uyruk",
        "RandevuyuVeren",
        # Previously removed from the schema; must remain permanently prohibited
        # even if a future prompt or context builder reintroduces them.
        "TCKimlikNo",
        "PasaportNo",
        "HastaGSM",
    }
)

_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    field: re.compile(rf"\b{re.escape(field)}\b", re.IGNORECASE)
    for field in PROHIBITED_PATIENT_FIELDS
}


class RemoteDataPolicyViolation(AppBaseException):
    """Raised when a payload bound for a remote LLM provider contains prohibited fields."""

    def __init__(self, matched_fields: list[str]):
        self.matched_fields = matched_fields
        super().__init__(
            "Remote LLM data policy violation: payload references prohibited patient-level "
            f"field(s): {', '.join(matched_fields)}. Remote providers may only receive schema "
            "metadata, query plans, SQL generation instructions, and anonymized aggregate results."
        )


def find_prohibited_fields(text: str) -> list[str]:
    """Returns the prohibited field names (if any) referenced in the given text.

    Args:
        text: Prompt or payload content about to be sent to a remote provider.

    Returns:
        list[str]: Sorted list of matched prohibited field names, empty if none found.
    """
    if not text:
        return []
    return sorted(field for field, pattern in _FIELD_PATTERNS.items() if pattern.search(text))


def enforce_remote_data_policy(*texts: str) -> None:
    """Rejects payloads bound for a remote LLM provider that reference prohibited fields.

    Args:
        *texts: One or more text fragments (e.g. system prompt, user prompt) to inspect.

    Raises:
        RemoteDataPolicyViolation: If any prohibited patient-level field is referenced.
    """
    matched: set[str] = set()
    for text in texts:
        matched.update(find_prohibited_fields(text))
    if matched:
        raise RemoteDataPolicyViolation(sorted(matched))
