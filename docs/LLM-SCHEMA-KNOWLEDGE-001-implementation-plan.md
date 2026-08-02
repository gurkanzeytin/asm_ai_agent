# LLM-SCHEMA-KNOWLEDGE-001 Implementation Plan

## Amaç

LLM'in `dbo.vw_RandevuRaporu` görünümündeki 24 kolonu yalnız isim olarak değil;
iş anlamı, güvenli operasyon, metrik, ilişki, PII politikası, kategori değeri ve
yanlış yorum riskiyle anlamasını sağlamak. Deterministik sözlüğün tanımadığı
sorularda yapılandırılmış ve doğrulanabilir QueryPlan üretmek.

## Tasarım kararı

Fine-tuning yerine runtime schema knowledge kullanılır. Şema bilgisi değiştiğinde
modeli yeniden eğitmek yerine katalog güncellenir. Bilgi ikinci bir elle tutulan
JSON dosyasına kopyalanmaz; mevcut canonical kaynaklardan oluşturulur:

- `column_intelligence.json`: 24 kolon ve kolon politikaları,
- `metric_catalog.json`: 48 metrik ve formüller,
- `relationship_catalog.json`: 22 analitik ilişki,
- `view_semantics.json`: görünüm amacı, kavram notları, tarih ve cohort anlamları.

## Uygulama adımları

1. Kategori değerleri için typed `known_values`, `values_verified` ve
   `value_notes` alanları ekle.
2. Dört kataloğu `SchemaKnowledge` modelinde runtime olarak birleştir.
3. Her kolon kartında ilişkili metrikleri ve relationship kimliklerini otomatik
   türet; kataloglar arasında kopya veri oluşturma.
4. LLM schema reasoning JSON sözleşmesine metrik, boyut, analiz tipi, zaman
   kolonu/scope, granularity, sıralama ve limit alanları ekle.
5. LLM kararındaki kolon, metrik, groupable dimension, analysis type ve zaman
   kolonunu kataloglara karşı doğrula.
6. Typed kararı `AgentState` üzerinden `RetrieveContextNode`'a taşı ve gerçek
   `QueryPlan` oluştur.
7. Typed LLM planında deterministik SQL şablonunu atla; LLM SQL üretimini plan
   compliance ve mevcut SQL Validator ile sınırla.

## Etkilenen alanlar

- `backend/app/semantics/catalog.py`
- `backend/app/semantics/schema_knowledge.py`
- `backend/app/application_models/schema_reasoning.py`
- `backend/app/services/schema_answerability.py`
- `backend/app/agent/state.py`
- `backend/app/agent/nodes/analyze_intent.py`
- `backend/app/agent/nodes/retrieve_context.py`
- `backend/app/planning/models.py`
- `backend/app/services/sql_service.py`
- `backend/app/prompts/schema_answerability.md`
- `backend/app/resources/column_intelligence.json`

API, frontend, database schema ve repository katmanı değişmez.

## Başarı ölçütleri

- Knowledge pack tam 24 kolon, 48 metrik ve en az 20 ilişki içerir.
- PII/selectable ve canlı-value-grounding politikası LLM bağlamında görünür.
- Typed plan gerçek katalog kimlikleri dışında değer kabul etmez.
- Önceki yıl gibi göreli zamanlar kesin ISO tarih aralığına çevrilir.
- Typed plan SQL'i mevcut read-only, allowlist, schema ve plan-compliance
  kapılarından geçmeden çalıştırılmaz.

## Verification

```bash
cd backend
../.venv/bin/python -m pytest -q tests/test_schema_reasoning_fallback.py \
  tests/test_deterministic_sql_pipeline.py tests/test_agent_intelligence.py \
  tests/test_semantic_mapping.py tests/test_plan_coverage.py
../.venv/bin/python -m pytest -q
```
