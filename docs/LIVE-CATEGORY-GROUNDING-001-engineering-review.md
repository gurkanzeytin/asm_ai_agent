# LIVE-CATEGORY-GROUNDING-001 — Engineering Review

## Mimari uyum

- Canlı doğrulama metadata'sı kanonik `column_intelligence.json` kataloğundadır.
- `SchemaKnowledge` bu metadata'yı LLM sağlayıcı katmanına taşır.
- API route veya UI içine kategori iş mantığı eklenmedi.
- Gerçek filtreler mevcut `ValueCatalog` ve planner üzerinden çözülür.

## Güvenlik ve doğruluk

- Hasta düzeyi veri okunmadı veya repoya yazılmadı.
- Uyruk tam listesi prompt'a gömülmedi; 149 değer canlı grounding'de kaldı.
- `known_values_complete=true` yalnız doğrulanmış değer sayısı katalog
  uzunluğuyla eşleşiyorsa yüklenebilir; katalog validasyonu drift'i engeller.
- Mükerrer görünen ülke değerleri iş kuralı varsayımıyla birleştirilmedi.
- `Irak/Irak 2` belirsizliği regresyon testiyle fail-closed tutuldu.

## Bilinen sınırlar

- `Ingiltere/Birleşik Krallık` ve `Dominik/Dominik Cum.` kaynak sistemde
  normalize edilmeden birleşik ülke analizi eksik sayım riski taşır.
- `ProtokolIslemState` kod-anlam eşlemesi hâlâ doğrulanmadı; kodlardan iş durumu
  çıkarılmamalıdır.
- Canlı farklı değer sayıları veri değiştikçe yeniden profillenmelidir.

## Verification

```bash
cd backend
PYTHONPATH=. ../.venv/bin/pytest -q tests/test_live_category_grounding.py
PYTHONPATH=. ../.venv/bin/pytest -q tests/test_schema_capability.py tests/test_value_resolver.py
```
