"""Domain synonym map for cross-language schema retrieval.

Maps common English query terms to their Turkish equivalents (pre-normalized,
diacritics stripped) so the keyword retriever can match English questions against
a Turkish-language database schema.

Organization:
    _MEDICAL       — clinical / hospital domain terms
    _REPORTING     — aggregation and analytical terms
    _SQL_CONCEPTS  — generic entity and data-type concepts

Design constraints:
    - Maximum ~40 entries total. Review before adding new terms.
    - All target values are diacritic-normalized at definition time (no runtime cost).
    - This is a transitional layer. Replace with an embedding-based retriever when
      query diversity grows beyond what a static map can cover.
"""

# ── Medical / hospital domain ─────────────────────────────────────────────────
_MEDICAL: dict[str, list[str]] = {
    "doctor":      ["doktor", "hekim", "uzman"],
    "patient":     ["hasta"],
    "appointment": ["randevu"],
    "department":  ["brans", "bolum"],
    "clinic":      ["klinik", "poliklinik"],
    "nurse":       ["hemsire"],
    "diagnosis":   ["teshis", "tani"],
    "treatment":   ["tedavi"],
    "medicine":    ["ilac", "recete"],
    "hospital":    ["hastane"],
    "surgery":     ["ameliyat", "cerrahi"],
    "ward":        ["servis", "klinik"],
}

# ── Reporting / aggregation terms ─────────────────────────────────────────────
_REPORTING: dict[str, list[str]] = {
    "report":    ["rapor"],
    "count":     ["sayi", "adet"],
    "number":    ["sayi", "numara"],
    "total":     ["toplam"],
    "average":   ["ortalama"],
    "highest":   ["en", "fazla", "maksimum"],
    "most":      ["en", "fazla"],
    "lowest":    ["en", "az", "minimum"],
    "least":     ["en", "az"],
    "schedule":  ["takvim", "program"],
    "list":      ["liste"],
}

# ── SQL / generic entity concepts ─────────────────────────────────────────────
_SQL_CONCEPTS: dict[str, list[str]] = {
    "name":   ["ad", "soyad", "isim"],
    "date":   ["tarih"],
    "time":   ["saat", "zaman"],
    "status": ["durum"],
    "type":   ["tur", "tip"],
    "id":     ["id", "no", "kod"],
    "phone":  ["telefon"],
    "email":  ["eposta", "mail"],
    "address": ["adres"],
}

# ── Public export ─────────────────────────────────────────────────────────────
SYNONYM_MAP: dict[str, list[str]] = {**_MEDICAL, **_REPORTING, **_SQL_CONCEPTS}
