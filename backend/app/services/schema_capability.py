"""Catalog-derived answers to schema capability questions; no SQL or LLM."""

from __future__ import annotations

import re

from app.application_models.schema_capability import SchemaCapabilityAnswer
from app.semantics import catalog
from app.semantics.catalog import ColumnSpec
from app.semantics.view_mapping import fold

_FIELD_MARKER = re.compile(r"\b(alan\w*|kolon\w*|sutun\w*|field\w*)\b")
_CAPABILITY_MARKER = re.compile(
    r"\bhangi\s+analiz\w*\b|"
    r"\b(?:ne|neler)\s+(?:ise\s+yarar|yapilabilir|analiz\s+edilebilir)\b|"
    r"\b(?:acikla|anlat)\w*\b"
)

_OPERATION_LABELS = {
    "filter": "filtreleme",
    "group_by": "kırılım/gruplama",
    "ranking": "sıralama",
    "distribution": "dağılım",
    "count": "kayıt sayma",
    "distinct_count": "tekil değer sayma",
    "average": "ortalama",
    "minimum": "minimum",
    "maximum": "maksimum",
    "date_filter": "tarih filtresi",
    "trend": "zaman eğilimi",
}


class SchemaCapabilityService:
    """Recognizes one-column meta questions and explains catalog capabilities."""

    def answer(self, question: str) -> SchemaCapabilityAnswer | None:
        folded = fold(question)
        if not _CAPABILITY_MARKER.search(folded):
            return None

        column = self._match_column(folded)
        if column is None:
            return None
        physical_name_mentioned = catalog.phrase_span(folded, column.column) is not None
        if not _FIELD_MARKER.search(folded) and not physical_name_mentioned:
            return None

        protected = column.pii or not column.selectable
        return SchemaCapabilityAnswer(
            column=column.column,
            business_name=column.business_name,
            markdown=self._build_markdown(column, protected=protected),
            protected=protected,
        )

    @staticmethod
    def _match_column(folded_question: str) -> ColumnSpec | None:
        matches: list[tuple[int, int, str, ColumnSpec]] = []
        for spec in catalog.load_column_catalog().columns:
            candidates = (
                (spec.business_name, 3),
                (spec.column, 2),
                *((synonym, 1) for synonym in spec.synonyms),
            )
            for term, priority in candidates:
                span = catalog.phrase_span(folded_question, term)
                if span is None:
                    continue
                token_length = span[1] - span[0]
                matches.append((token_length, priority, spec.column, spec))
        if not matches:
            return None
        matches.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return matches[0][3]

    @staticmethod
    def _build_markdown(spec: ColumnSpec, *, protected: bool) -> str:
        metric_catalog = catalog.load_metric_catalog()
        related_metrics = [
            metric.name
            for metric in metric_catalog.metrics
            if spec.column in metric.required_columns
            and metric.status != "requires_verified_mapping"
        ]
        column_by_name = catalog.load_column_catalog()
        safe_related_columns = [
            related.business_name
            for related in column_by_name.columns
            if related.column in spec.related_columns and not related.pii
        ]
        operations = [
            _OPERATION_LABELS.get(operation, operation.replace("_", " "))
            for operation in spec.supported_operations
        ]

        lines = [
            f"# {spec.business_name}",
            "",
            f"**Teknik kolon:** `{spec.column}`",
            "",
            spec.description,
            "",
        ]
        if protected:
            lines.extend(
                [
                    "## Güvenlik sınırı",
                    "",
                    "Bu kolon kişisel/korumalı veri kapsamındadır. Ham değerleri, "
                    "tekil kayıtları veya kişi listesini göstermem; yalnız kimlik "
                    "açığa çıkarmayan ve katalogda doğrulanmış toplu analizler kullanılabilir.",
                    "",
                ]
            )
        elif not spec.listable_default:
            lines.extend(
                [
                    "Bu kolon varsayılan ham liste alanı değildir; analitik amaçla "
                    "filtre, kırılım veya toplulaştırma içinde kullanılır.",
                    "",
                ]
            )

        lines.extend(["## Desteklenen kullanım", ""])
        if operations:
            lines.extend(f"- {operation}" for operation in operations)
        else:
            lines.append("- Bu kolon için doğrudan bir analitik işlem tanımlanmamış.")

        lines.extend(["", "## Doğrulanmış ilgili metrikler", ""])
        if related_metrics:
            lines.extend(f"- {metric}" for metric in related_metrics[:8])
        else:
            lines.append("- Bu kolona doğrudan bağlı doğrulanmış bir metrik bulunmuyor.")

        if safe_related_columns:
            lines.extend(["", "## İlişkili kolonlar", ""])
            lines.extend(f"- {name}" for name in safe_related_columns[:6])

        if spec.values_verified and spec.known_values and not protected:
            lines.extend(["", "## Doğrulanmış örnek değerler", ""])
            lines.extend(f"- {value}" for value in spec.known_values[:8])

        if spec.common_mistakes:
            lines.extend(["", "## Dikkat", ""])
            lines.extend(f"- {warning}" for warning in spec.common_mistakes[:5])

        return "\n".join(lines)
