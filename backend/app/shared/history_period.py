"""Shared language helpers for unbounded historical-period references."""

import re

UNBOUNDED_HISTORY_FOLDED_PATTERN = re.compile(
    r"\b(?:daha\s+once\w*|onceden\w*|gecmiste\w*|evvelce\w*)\b"
)

_UNBOUNDED_HISTORY_ORIGINAL_PATTERN = re.compile(
    r"\b(?:daha\s+(?:önce|once)\w*|(?:önceden|onceden)\w*|"
    r"(?:geçmişte|gecmiste)\w*|evvelce\w*)\b",
    flags=re.IGNORECASE,
)


def has_unbounded_history_marker(folded_text: str) -> bool:
    """Return whether folded Turkish text names history without a boundary."""
    return UNBOUNDED_HISTORY_FOLDED_PATTERN.search(folded_text) is not None


def replace_unbounded_history_marker(text: str, replacement: str) -> str:
    """Replace the first unbounded history marker with a bounded period."""
    return _UNBOUNDED_HISTORY_ORIGINAL_PATTERN.sub(replacement, text, count=1)
