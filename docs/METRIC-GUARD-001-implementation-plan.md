# METRIC-GUARD-001 Implementation Plan

## Amaç

Görülmemiş soru denetimindeki metrik uyuşmazlıklarını gerçek ajan hataları ile
ölçüm yanlış-pozitifleri olarak ayırmak; doğrulanmamış iş kurallarında yanlış SQL
üretimini engellemek.

## Varsayımlar

- `count_rows_grouped + fixed_dimension`, SQL açısından
  `appointment_count + aynı dimension` planıyla eşdeğerdir.
- `requires_verified_mapping` durumundaki metriklerin SQL koşulu canlı kaynak
  değerleri görülmeden tahmin edilemez.
- Katalogdaki doğrulanmış bir metriğin görünen adı kullanıcı tarafından doğrudan
  sorulabilir olmalıdır.

## Değişiklikler

1. Doğrulanmış metrik adlarını, mevcut synonym eşleşmesi yoksa güvenli fallback
   sözlüğü olarak kullan.
2. Doğrulanmamış metrik adı veya synonym'i görüldüğünde clarification üret.
3. Stres denetiminde sabit-boyutlu COUNT eşdeğerliğini kabul et.
4. Doğrulanmamış metrik vakalarını beklenen güvenli clarification olarak ölç.
5. Golden beklentilerini yeni fail-closed sözleşmesiyle hizala.
6. Odaklı, golden ve tam regresyon testlerini çalıştır.

## Etkilenen dosyalar

- `backend/app/semantics/catalog.py`
- `backend/app/services/query_analyzer.py`
- `backend/tools/evaluation/question_variations.py`
- `backend/app/resources/golden_dataset.json`
- `backend/app/resources/asm_24_column_golden_eval.json`
- `backend/tests/test_agent_intelligence.py`
- `backend/tests/test_question_variation_audit.py`

## Rollout

Şema veya veritabanı migrasyonu yoktur. Canlı değer eşlemesi pazartesi
doğrulandıktan sonra ilgili metrikler `requires_verified_mapping` durumundan
çıkarılıp formülleri ayrı bir testli dilimde etkinleştirilebilir.
