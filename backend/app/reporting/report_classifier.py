import logging
import re
import unicodedata
from enum import StrEnum

from app.application_models.workflow_models import QueryResult
from app.core.config import settings

logger = logging.getLogger(__name__)


class ReportType(StrEnum):
    """Deterministic report categories derived from executed SQL results."""

    SINGLE_VALUE = "single_value"
    SINGLE_ROW = "single_row"
    TABLE = "table"
    EMPTY = "empty"
    ANALYTICAL = "analytical"


class ReportClassifier:
    """Classifies SQL result shapes without using question text, SQL text, or LLMs."""

    def __init__(self, analytical_row_threshold: int | None = None) -> None:
        self.analytical_row_threshold = (
            analytical_row_threshold
            if analytical_row_threshold is not None
            else getattr(settings, "REPORT_ANALYTICAL_ROW_THRESHOLD", 20)
        )

    def classify(
        self,
        query_result: QueryResult,
        question: str | None = None,
        sql: str | None = None,
    ) -> ReportType:
        intent = self._detect_intent(question or "", sql or "")

        if query_result.row_count == 0 or not query_result.rows:
            report_type = ReportType.EMPTY
            self._log_classification(intent, report_type)
            return report_type

        if intent == "ANALYTICAL":
            report_type = ReportType.ANALYTICAL
            self._log_classification(intent, report_type)
            return report_type

        if self._is_count_result(query_result):
            report_type = ReportType.SINGLE_VALUE
            self._log_classification(intent, report_type)
            return report_type

        if query_result.row_count == 1:
            row = query_result.rows[0]
            if len(row) == 1:
                report_type = ReportType.SINGLE_VALUE
            else:
                report_type = ReportType.SINGLE_ROW
            self._log_classification(intent, report_type)
            return report_type

        report_type = ReportType.TABLE
        self._log_classification(intent, report_type)
        return report_type

    def _detect_intent(self, question: str, sql: str) -> str:
        text = _normalize_text(f"{question} {sql}")

        analytical_patterns = (
            r"\btrend\w*\b",
            r"\begilim\w*\b",
            r"\banaliz\w*\b",
            r"\banaly[sz]e\w*\b",
            r"\banalysis\b",
            r"\binsight\w*\b",
            r"\bicgoru\w*\b",
            r"\bperformans\w*\b",
            r"\bperformance\b",
            r"\bkarsilastir\w*\b",
            r"\bkarsilastirma\w*\b",
            r"\bcompare\w*\b",
            r"\bcomparison\w*\b",
        )
        if any(re.search(pattern, text) for pattern in analytical_patterns):
            return "ANALYTICAL"

        list_patterns = (
            r"\blistele\b",
            r"\blist\b",
            r"\bshow\b",
            r"\bgoster\b",
            r"\bgetir\b",
            r"\bfind\b",
            r"\bselect\s+\*",
        )
        if any(re.search(pattern, text) for pattern in list_patterns):
            return "LIST"

        summary_patterns = (
            r"\bkac\b",
            r"\bsayi\b",
            r"\bsayisi\b",
            r"\bcount\b",
            r"\btotal\b",
            r"\btoplam\b",
            r"\ben cok\b",
            r"\ben fazla\b",
            r"\bmax\b",
            r"\bmin\b",
            r"\bavg\b",
            r"\baverage\b",
            r"\bsum\b",
        )
        if any(re.search(pattern, text) for pattern in summary_patterns):
            return "SUMMARY"

        return "TABLE"

    def _is_count_result(self, query_result: QueryResult) -> bool:
        if query_result.row_count != 1 or len(query_result.rows[0]) != 1:
            return False
        column = next(iter(query_result.rows[0].keys()), "")
        normalized = _normalize_text(column)
        return any(marker in normalized for marker in ("count", "sayi", "sayisi", "total", "toplam"))

    def _log_classification(self, intent: str, report_type: ReportType) -> None:
        logger.info(
            "\n================ REPORT CLASSIFIER ================\n"
            f"Intent\n\n{intent}\n\n"
            f"Report Type\n\n{report_type.name}\n\n"
            f"LLM Invoked\n\n{report_type == ReportType.ANALYTICAL}\n"
            "===================================================",
            extra={
                "intent": intent,
                "report_type": report_type.value,
                "llm_invoked": report_type == ReportType.ANALYTICAL,
            },
        )


def _normalize_text(value: str) -> str:
    text = value.lower().translate(
        str.maketrans(
            {
                "ı": "i",
                "ğ": "g",
                "ş": "s",
                "ç": "c",
                "ö": "o",
                "ü": "u",
            }
        )
    )
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))
