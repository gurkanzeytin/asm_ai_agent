"""Safe, catalog-derived natural-language examples for every schema column.

Examples are generated from column capabilities instead of being maintained as a
second question catalog.  This keeps the UI, capability answers, and LLM schema
context aligned when a column's metadata changes.
"""

from __future__ import annotations

from app.semantics.catalog import ColumnSpec


def column_question_examples(spec: ColumnSpec) -> list[str]:
    """Return deterministic, PII-safe examples supported by one column card."""
    label = spec.business_name.casefold()
    capability_examples = [
        f"{spec.business_name} sütunuyla hangi soruları sorabilirim?",
        f"{spec.business_name} alanı için desteklenen analizleri ve sınırları açıkla.",
    ]

    # A protected/non-selectable field may be explained, but must never be
    # advertised as a raw-value or person-list query surface.
    if spec.pii or not spec.selectable:
        return capability_examples

    special_examples = {
        "Id": [
            "2025 yılındaki toplam randevu sayısı nedir?",
            "2025 yılında aylara göre randevu sayısını göster.",
        ],
        "BaslangicTarihi": [
            "2025 yılında randevu sayısının aylık değişimini göster.",
            "Randevuların haftanın günlerine ve saatlere göre dağılımı nedir?",
        ],
        "BitisTarihi": [
            "2025 randevularının en erken ve en geç bitiş tarihleri nedir?",
            "Bitiş tarihi dolu olan randevuların sayısı nedir?",
        ],
        "RandevuSuresi": [
            "2024 yılındaki ortalama randevu süresi nedir?",
            "Bölümlere göre minimum, ortalama ve maksimum randevu süresini göster.",
        ],
        "HastaId": [
            "2025 yılındaki tekil hasta sayısı nedir?",
            "Şubelere göre tekil hasta sayısını karşılaştır.",
        ],
        "DogumTarihi": [
            "Yaş gruplarına göre randevu dağılımını göster.",
            "2025 randevularında ortalama hasta yaşı nedir?",
        ],
        "HastaId2": [
            "Hasta kimliği ile ikincil hasta kimliği eşleşmeyen kayıtların sayısı nedir?",
            "İkincil hasta kimliği boş olan randevuların oranı nedir?",
        ],
        "ProtokolIslemState": [
            "Protokol işlem durumu kodlarına göre randevu dağılımını göster.",
            "Protokol işlem durumu boş olan kayıtların oranı nedir?",
        ],
        "ProtokolAcilisTarihi": [
            "Protokol açılış tarihi boş olan randevuların oranı nedir?",
            "Randevu başlangıcı ile protokol açılışı arasındaki ortalama süre nedir?",
        ],
        "CreatedDate": [
            "2025 boyunca oluşturulan randevu sayısını aylara göre göster.",
            "Randevunun oluşturulması ile başlangıcı arasındaki ortalama süre nedir?",
        ],
    }
    if spec.column in special_examples:
        return [*special_examples[spec.column], capability_examples[0]]

    if spec.groupable:
        return [
            f"2025 yılında {label} bazında randevu sayısını göster.",
            f"{spec.business_name} kırılımında randevu dağılımını ve oranlarını göster.",
            f"{spec.business_name} bazında gelmeme oranını karşılaştır.",
            capability_examples[0],
        ]

    operations = set(spec.supported_operations)
    if {"avg", "average"} & operations or spec.aggregatable == "numeric":
        return [
            f"2025 yılında ortalama {label} nedir?",
            f"Şubelere göre minimum ve maksimum {label} değerlerini göster.",
            capability_examples[0],
        ]

    return capability_examples
