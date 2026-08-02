# SCHEMA-CAPABILITY-001 Implementation Plan

## Amaç

“Bu kolonla hangi analizleri yapabilirsin?”, “Bu alan ne işe yarar?” gibi
meta-şema sorularını SQL sorgusu gibi çalıştırmadan, merkezi kolon ve metrik
kataloglarından güvenli ve açıklayıcı biçimde yanıtlamak.

## Tasarım

1. Meta-soru grameri deterministik olarak tanınır.
2. Sorudaki kolon, iş adı/fiziksel ad/eşanlamlılar arasından en özgül eşleşmeyle
   bulunur.
3. Tipli `SchemaCapabilityAnswer` üretilir.
4. Intent sınıflandırıcıdan önce graph kısa devre edilir.
5. Ayrı node, cevabı `GeneratedReport` olarak döndürür.
6. SQL üretimi, SQL doğrulama, database execution ve LLM aşamaları çalışmaz.

## Cevap içeriği

- Teknik kolon adı ve iş açıklaması.
- Desteklenen işlemler.
- Yalnız doğrulanmış ilgili metrikler.
- Güvenli ilişkili kolonlar.
- Varsa doğrulanmış kategori değerleri.
- Yaygın hata ve karıştırma uyarıları.
- PII/selectable=false kolonlarında açık ham-veri sınırı.

## Etkilenen dosyalar

- `backend/app/application_models/schema_capability.py`
- `backend/app/services/schema_capability.py`
- `backend/app/agent/nodes/generate_schema_capability.py`
- `backend/app/agent/state.py`
- `backend/app/agent/nodes/analyze_intent.py`
- `backend/app/agent/graph.py`
- `backend/tools/evaluation/question_variations.py`
- `backend/tests/test_schema_capability.py`
- `backend/tests/test_question_variation_audit.py`

## Rollout

Database migrasyonu ve API sözleşmesi değişikliği yoktur. Yeni yol salt katalog
okur ve mevcut `GeneratedReport` sözleşmesini kullanır.
