# LLM-SCHEMA-KNOWLEDGE-001 Walkthrough

## LLM'in aldığı bilgi

`SchemaKnowledge` her kolon için aşağıdaki kartı runtime oluşturur:

```text
RandevuSuresi
├─ iş anlamı: planlanan randevu süresi (dakika)
├─ operasyonlar: avg, min, max, sum, filter
├─ ilişkili kolonlar: BaslangicTarihi, BitisTarihi
├─ ilişkili metrikler: appointment_duration_average/minimum/maximum, ...
├─ yanlış yorum: fiili süreyle aynı kabul edilmez
├─ PII/selectable/filterable/groupable politikası
└─ kategori value grounding durumu
```

Bu kartlar 24 kolonun tamamı için oluşturulur. Ayrıca 48 metrik formül tipi,
gerekli kolonlar, sonuç tipi ve 22 ilişki LLM bağlamına eklenir.

## Kategori değer politikası

- `RandevuDurumu`: doğrulanmış; Beklemede, Gelmedi, Gerçekleşti, Giriş
  Yapılmış, İşlem Sürmekte.
- `CinsiyetId`: doğrulanmış; E, K, D.
- `RandevuTipiAdi`: kısmi örnek küme; canlı DB başka değerler içerebilir.
- `Uyruk`: yalnız ana ülke `Türkiye` doğrulanmış; diğer değerler canlı grounding
  gerektirir.
- `ProtokolIslemState` ve örnek değer verilmeyen kategoriler:
  `live_db_required`; LLM anlam veya literal uyduramaz.

## Typed soru akışı

Örnek:

```text
Geçen seneki görüşmeler ne kadar vakit almış?
```

LLM schema reasoning kararı:

```json
{
  "status": "answerable",
  "supporting_metrics": ["appointment_duration_average"],
  "supporting_columns": ["RandevuSuresi", "BaslangicTarihi"],
  "dimension_columns": [],
  "analysis_type": "average",
  "time_column": "BaslangicTarihi",
  "time_scope": "previous_year"
}
```

`RetrieveContextNode`, `previous_year` değerini çalışılan tarihe göre 1 Ocak–31
Aralık ISO aralığına çevirir ve `planning_source=llm_schema_reasoning` olan typed
QueryPlan üretir. SQL LLM tarafından oluşturulur; ancak exact metric formula,
tarih sınırları ve kolonlar plan compliance tarafından kontrol edilir. Ardından
read-only SQL Validator ve schema identifier doğrulaması çalışır.

## Fallback davranışı

LLM yalnız cevaplanabilirlik söyleyip metric/analysis planı veremezse eski
schema-only LLM SQL fallback korunur. Uydurma kolon/metrik, non-groupable boyut,
geçersiz analiz tipi veya zamansal olmayan time column tüm kararı reddeder.

## Doğrulama sonucu

- Odaklı knowledge/planner/SQL regresyonları: 316 geçti.
- Tam backend paketi: 2242 geçti, 1 atlandı.
- Golden audit: 253 güvenli davranış ve 243 deterministik demo-hazır soru
  korundu.
- Ruff: geçti.
- JSON katalog doğrulaması: geçti.
- Canlı SQL Server kullanılmadı.
