"""Text → `MetricPredicate`: the parsing side of the metric algebra.

The metric catalog freezes each condition into a formula, so a question whose
condition the catalog never anticipated had no way to be expressed. The escape
is to build the condition as DATA — but the existing parsers bind wording to ONE
column each (`QueryPlanner._age_filter` is four regexes hard-wired to
DogumTarihi), so the identical Turkish construction on any other column is
simply lost: "60 yaş üstü" works, "30 dakikadan uzun" does not.

This module parses the construction once and resolves the column from the
question instead, so a new comparable column costs a catalog entry rather than a
new function.

Every predicate returned here is still re-validated by the SQL builder (column
against the real column catalog, operator against its own allow-list) before it
can reach SQL.
"""

from __future__ import annotations

import re

from app.planning.models import MetricPredicate
from app.semantics.catalog import fold, load_column_catalog

# Turkish comparison wording → operator. Roots only: `_comparator` matches by
# prefix so inflected forms ("uzunsa", "fazlası", "altındaki") need no entry.
# Both duration wording ("uzun"/"kısa") and quantity wording ("fazla"/"az")
# appear because the same construction serves both.
_GREATER_ROOTS = ("uzun", "fazla", "cok", "buyuk", "ustu", "uzeri", "asan", "gecen", "yukari")
_LESS_ROOTS = ("kisa", "az", "kucuk", "alti", "altinda", "asagi", "dusuk")
# "en az N" / "en fazla N" invert to inclusive bounds — "en az 30 dakika" means
# 30 and above, not strictly above.
_INCLUSIVE_PREFIXES = {"en"}

# Unit wording → the column it measures. A unit is the strongest column signal
# there is: "dakika" can only be RandevuSuresi in this view.
_UNIT_COLUMNS: dict[str, str] = {
    "dakika": "RandevuSuresi",
    "dakikadan": "RandevuSuresi",
    "dk": "RandevuSuresi",
}

# Columns whose value a numeric threshold may be compared against. Age is
# deliberately absent: `QueryPlanner._age_filter` already renders it as a
# DATEDIFF expression, and two parsers claiming the same wording would fight.
_COMPARABLE_COLUMNS = frozenset({"RandevuSuresi"})

# Turkish attaches case suffixes to numerals with an apostrophe ("15'ten az",
# "100'ün üzerinde"), so the bare-digit form has to be recovered first.
_NUMBER = re.compile(r"^(\d{1,6})(?:['’`]\w*)?$")


def _comparator(token: str) -> str | None:
    if any(token.startswith(root) for root in _GREATER_ROOTS):
        return ">"
    if any(token.startswith(root) for root in _LESS_ROOTS):
        return "<"
    return None


def _column_for(tokens: list[str], number_index: int) -> str | None:
    """Which column the number is a bound on.

    A unit right after the number wins ("30 DAKİKAdan uzun"); otherwise any
    comparable column named anywhere in the question is used, which covers
    "randevu süresi 30'dan uzun olanlar".
    """
    for token in tokens[number_index + 1 : number_index + 3]:
        for unit, column in _UNIT_COLUMNS.items():
            if token.startswith(unit):
                return column

    question = " ".join(tokens)
    for spec in load_column_catalog().columns:
        if spec.column not in _COMPARABLE_COLUMNS:
            continue
        if any(fold(synonym) in question for synonym in (spec.business_name, *spec.synonyms)):
            return spec.column
    return None


# Unit noun per comparable column, for building a readable Turkish label.
_COLUMN_UNITS: dict[str, str] = {"RandevuSuresi": "dakika"}
_BOUND_WORDING: dict[str, str] = {
    ">": "{value} {unit}dan uzun",
    "<": "{value} {unit}dan kısa",
    ">=": "{value} {unit} ve üzeri",
    "<=": "{value} {unit} ve altı",
}


def threshold_label(predicate: MetricPredicate) -> str:
    """Turkish name for a threshold cohort ("30 dakikadan uzun randevu")."""
    unit = _COLUMN_UNITS.get(predicate.column, "")
    value = predicate.values[0]
    rendered = int(value) if float(value).is_integer() else value
    wording = _BOUND_WORDING.get(predicate.operator, "{value} {unit}")
    return f"{wording.format(value=rendered, unit=unit).strip()} randevu"


def extract_measure_threshold(question: str) -> MetricPredicate | None:
    """Parses "<N> <unit?> <comparison>" into a bound on a comparable column.

    Returns None — never a guess — when no number, no comparison wording, or no
    resolvable column is present. The bound is whatever number the user wrote:
    nothing here is specific to any particular value.
    """
    tokens = fold(question).split()
    for index, token in enumerate(tokens):
        number = _NUMBER.match(token)
        if not number:
            continue

        # Trailing form: "30 dakikadan UZUN", "15'ten AZ".
        operator = None
        for offset in range(index + 1, min(index + 4, len(tokens))):
            operator = _comparator(tokens[offset])
            if operator:
                break

        # Leading form: "EN AZ 30 dakika" — same construction, inverted word
        # order, and inclusive ("en az 30" includes 30 itself).
        if operator is None and index >= 2 and tokens[index - 2] in _INCLUSIVE_PREFIXES:
            leading = _comparator(tokens[index - 1])
            if leading is not None:
                operator = ">=" if leading == "<" else "<="
        if operator is None:
            continue

        column = _column_for(tokens, index)
        if column is None:
            continue
        return MetricPredicate(
            column=column, operator=operator, values=[float(number.group(1))]
        )
    return None
