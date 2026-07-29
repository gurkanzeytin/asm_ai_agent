"""Meta-conversation memory: answering questions ABOUT the chat itself.

Questions like "Son sorumda hangi kırılımı istemiştim?", "Bir önceki cevabında
hangi metrik vardı?", "Bu sohbette belirttiğim son yıl neydi?" are not database
questions — the appointment view holds no record of what the user previously
asked. They are answered deterministically from the retained
`ConversationContext` (latest dimension/metric/date + the recent question
window), never by generating SQL (2026-07-29, live UI meta-conversation
findings). Detection is deliberately gated on an explicit self/conversation
reference so an ordinary data question ("2024 yılında kaç randevu") is never
mistaken for one.
"""

from __future__ import annotations

from app.context.models import ConversationContext
from app.reporting.presentation import get_dimension_label, get_metric_label

# The question must refer to THIS conversation (the user's own prior turns or
# the assistant's prior answer) — not merely mention a year/breakdown, which a
# normal data question does too. "bir onceki" is intentionally excluded on its
# own: "bir önceki ay" is an ordinary relative date, not a memory reference.
_SELF_REFERENCE_MARKERS: tuple[str, ...] = (
    "sorumda",
    "soruma",
    "sorularimda",
    "sordugum",
    "ne sordum",
    "ne istedim",
    "ne istemis",
    "istemistim",
    "sormustum",
    "onceki cevab",
    "onceki yanit",
    "onceki soru",
    "son cevab",
    "son yanit",
    "bu sohbet",
    "bu konusma",
    "benden gelen",
    "sana ne sordum",
)

# Attribute the meta-question asks about, most-specific first.
_DATE_MARKERS = ("yil", "yili", "tarih", "donem", "ay ")
_DIMENSION_MARKERS = ("kirilim", "gruplama", "bazinda", "hangi grup")
_METRIC_MARKERS = ("metrik", "olcut", "hangi oran")


def detect_conversation_memory_question(folded_question: str) -> str | None:
    """Returns the meta-question category ('date' | 'dimension' | 'metric' |
    'recap') when the question asks about the conversation itself, else None.

    `folded_question` is the diacritic-insensitive, lower-cased form.
    """
    if not any(marker in folded_question for marker in _SELF_REFERENCE_MARKERS):
        return None
    if any(marker in folded_question for marker in _DATE_MARKERS):
        return "date"
    if any(marker in folded_question for marker in _DIMENSION_MARKERS):
        return "dimension"
    if any(marker in folded_question for marker in _METRIC_MARKERS):
        return "metric"
    # A bare "ne sordum" / "önceki sorularım neydi" recaps the recent window.
    return "recap"


def _recent_questions(context: ConversationContext, limit: int = 3) -> list[str]:
    seen: list[str] = []
    for turn in context.turns[-limit:]:
        question = (turn.question or "").strip()
        if question:
            seen.append(question)
    return seen


def build_conversation_memory_answer(
    context: ConversationContext, category: str
) -> str | None:
    """Builds a Türkçe plain-text answer from the retained context, or None when
    there is no conversation history to draw on (the turn then falls through to
    normal handling instead of asserting an empty memory)."""
    recent = _recent_questions(context)
    if not context.turns:
        return None

    if category == "date":
        if context.date_expression:
            body = f"Bu sohbette belirttiğiniz son tarih/dönem: **{context.date_expression}**."
        else:
            body = "Bu sohbette henüz belirli bir tarih ya da yıl belirtmediniz."
    elif category == "dimension":
        if context.dimensions:
            labels = ", ".join(get_dimension_label(d) for d in context.dimensions)
            body = f"Son sorgunuzun kırılımı (gruplaması): **{labels}**."
        else:
            body = "Son sorgunuzda özel bir kırılım (gruplama) istemediniz."
    elif category == "metric":
        if context.metrics:
            labels = ", ".join(get_metric_label(m) for m in context.metrics)
            body = f"Son sorgunuzun metriği: **{labels}**."
        else:
            body = (
                "Son sorgunuzda özel bir metrik belirtmediniz; varsayılan olarak "
                "randevu sayısı kullanıldı."
            )
    else:  # recap
        if recent:
            listed = "\n".join(f"{index}. {q}" for index, q in enumerate(recent, 1))
            return "\n".join(
                ["# Bu Sohbetteki Son Sorularınız", "", listed]
            )
        return "Bu sohbette henüz kaydedilmiş bir soru geçmişi yok."

    lines = ["# Sohbet Hafızası", "", body]
    if recent:
        lines.extend(["", "_Son sorularınız:_"])
        lines.extend(f"- {q}" for q in recent)
    return "\n".join(lines)
