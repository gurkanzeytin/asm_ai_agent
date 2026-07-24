import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from app.analytics.models import AnalyticsResult
from app.application_models.workflow_models import QueryResult

ResponseMode = Literal["answer", "sql", "data", "visualization"]

_TERMINAL_ANSWER_OUTCOMES = {
    "OUT_OF_SCOPE",
    "ASK_CLARIFICATION",
    "NO_RESULT_GUIDANCE",
    "SAFE_ERROR",
}
_SQL_MARKER = re.compile(r"\b(sql|sorgu|sorgusunu|sorguyu)\b")
_SQL_ONLY_MARKER = re.compile(
    r"\b(sadece|yalniz)\b.{0,30}\b(sql|sorgu|sorgusunu|sorguyu)\b"
    r"|\b(sql|sorgu|sorgusunu|sorguyu)\b.{0,40}\b"
    r"(ver\w*|yaz\w*|uret\w*|olustur\w*|goster\w*)\b"
    r"|\bcalistirma\b"
)
# "veri(?!r)" excludes "verir"/"verirsin"/"verir misin" etc - conjugated
# forms of the VERB "vermek" (to give, as in "SQL'ini verir misin?" = "would
# you give me the SQL?"), which otherwise false-positive-matched the NOUN
# "veri" (data) + \w* and silently demoted a plain "give me the SQL"
# request from response_mode "sql" to "data", triggering an unrelated
# "which data do you mean?" clarification (2026-07-24 real UI bug report).
# Genuine noun inflections (verisi/verileri/veriyi/verinin/...) are
# unaffected - none of them have "r" immediately after "veri".
_DATA_MARKER = re.compile(
    r"\b(veri(?!r)\w*|kayit\w*|liste\w*|getir\w*|cek\w*|tablo\w*|sonuc\w*)\b"
)
# "calistir(?!ma\b)" excludes "çalıştırma" ("don't run [it]") - the Turkish
# negation suffix "-ma/-me" attaches directly to the verb stem with no space,
# so a bare \w* wildcard can't tell "çalıştır" (run, positive) from its own
# negation. _SQL_ONLY_MARKER above already treats bare "calistirma" as an
# explicit SQL-only signal ("...sorguyu ver, çalıştırma") - without this
# exclusion, this marker matched the same word as an EXECUTION request and
# silently overrode that SQL-only signal, executing and returning "data"
# mode for a question that explicitly asked NOT to run it (2026-07-24, live
# multi-turn testing).
_EXECUTION_MARKER = re.compile(r"\b(calistir(?!ma\b)\w*|cek\w*|getir\w*|listele\w*|sonuc\w*)\b")
_VISUAL_MARKER = re.compile(
    r"\b(grafik\w*|grafig\w*|chart|gorsel\w*|ciz\w*|cizgi\w*|bar|"
    r"sutun\w*|pasta|oranlama)\b"
)
_ANSWER_MARKER = re.compile(
    r"\b(yanitla|cevapla|yorum|yorumla|ozet|rapor|analiz|acikla|"
    r"degerlendir|ne anlama|sonucunu yorumla)\b"
)
# "X'i listeleyecek SQL sorgusu" - a future-tense participle (-ecek/-acak)
# directly modifying "sql/sorgu" is a relative clause describing what the SQL
# will DO once run, not an imperative to run/fetch data now. Without this,
# "listeleyecek"/"getirecek" right before "sql sorgusu" wrongly reads as a
# data/execution marker and demotes an SQL-only request ("...sorgusunu
# oluşturur musun") down to "data" mode, silently executing and showing a
# table the user never asked for.
_PARTICIPLE_MODIFYING_SQL = re.compile(r"\b\w+(?:ecek|acak)\b(?=\s+(?:sql|sorgu\w*)\b)")


def _strip_sql_describing_participle(folded: str) -> str:
    return _PARTICIPLE_MODIFYING_SQL.sub("", folded)


class OutputPolicy(BaseModel):
    response_mode: ResponseMode = Field(..., description="Primary user-facing output mode.")
    visible_sections: list[str] = Field(
        default_factory=list,
        description="Sections the client should present by default.",
    )


def determine_requested_response_mode(question: str) -> ResponseMode | None:
    """Infers an explicit presentation request from the user's wording."""
    folded = _fold(question)
    if _VISUAL_MARKER.search(folded):
        return "visualization"
    intent_probe = _strip_sql_describing_participle(folded)
    has_data_marker = bool(_DATA_MARKER.search(intent_probe))
    if _SQL_ONLY_MARKER.search(folded) and not (
        has_data_marker or _EXECUTION_MARKER.search(intent_probe)
    ):
        return "sql"
    if has_data_marker or (
        _SQL_MARKER.search(folded) and _EXECUTION_MARKER.search(intent_probe)
    ):
        return "data"
    return None


def determine_requested_visible_sections(question: str) -> list[str]:
    """Infers the exact artifact families explicitly requested by the user."""
    folded = _fold(question)
    intent_probe = _strip_sql_describing_participle(folded)
    wants_visual = bool(_VISUAL_MARKER.search(folded))
    wants_sql = bool(_SQL_MARKER.search(folded)) and (
        bool(_SQL_ONLY_MARKER.search(folded))
        or any(term in folded for term in ("sql ver", "sql yaz", "sql olustur", "sorgu ver"))
    )
    wants_data = bool(_DATA_MARKER.search(intent_probe)) or (
        bool(_SQL_MARKER.search(folded)) and bool(_EXECUTION_MARKER.search(intent_probe))
    )
    wants_answer = bool(_ANSWER_MARKER.search(folded))

    sections: list[str] = []
    if wants_answer:
        sections.append("answer")
    if wants_sql:
        sections.append("sql")
    if wants_data:
        sections.append("table")
    if wants_visual:
        sections.append("chart")
    return sections


def _fold(text: str) -> str:
    lowered = text.replace("İ", "i").replace("I", "i").replace("ı", "i").lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def determine_output_policy(
    *,
    question: str,
    outcome: str | None,
    generated_sql: str | None,
    query_result: QueryResult | None,
    analytics: AnalyticsResult | None,
) -> OutputPolicy:
    """Determines which successful artifacts should be visible to the user."""
    if outcome in _TERMINAL_ANSWER_OUTCOMES:
        return OutputPolicy(response_mode="answer", visible_sections=["answer"])

    requested_mode = determine_requested_response_mode(question)
    requested_sections = determine_requested_visible_sections(question)
    if requested_mode == "visualization":
        return OutputPolicy(
            response_mode="visualization",
            visible_sections=requested_sections or ["chart"],
        )
    if generated_sql and requested_mode == "sql":
        return OutputPolicy(response_mode="sql", visible_sections=requested_sections or ["sql"])
    if query_result and requested_mode == "data":
        return OutputPolicy(response_mode="data", visible_sections=requested_sections or ["table"])

    visible = ["answer"]
    if analytics and analytics.displayable_kpis:
        visible.append("metrics")
    return OutputPolicy(response_mode="answer", visible_sections=visible)
