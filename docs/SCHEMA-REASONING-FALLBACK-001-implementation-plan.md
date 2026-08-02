# SCHEMA-REASONING-FALLBACK-001 Implementation Plan

## Amaç

Deterministik sözlüklerin tanımadığı fakat `dbo.vw_RandevuRaporu` görünümündeki
kolonlardan hesaplanabilen doğal dil sorularını erken `OUT_OF_SCOPE` sonucuna
göndermek yerine mevcut güvenli LLM SQL hattına geçirmek.

## Sorun

`AnswerabilityGuard`, bilinen entity, tarih+operasyon veya katalog terimi
bulamadığında `no_domain_signal` üretir. Graph bu kararı SQL şema erişiminden
önce `generate_out_of_scope` düğümüne yönlendirir. Böylece yeni bir paraphrase,
LLM'in şemayla mantık yürütme fırsatı olmadan reddedilebilir.

## Uygulama dilimi

1. Yalnız `no_domain_signal` kararı için bounded LLM ikinci görüşü çalıştır.
2. LLM'e 24 kolon, 48 metrik ve doğrulanmış kapsam-dışı kavramları ver.
3. Yalnız JSON karar kabul et; cevaplanabilir kararında en az bir gerçek kolon
   ve en az 0.70 güven iste.
4. Uydurma kolon/metrik, bozuk çıktı, düşük güven veya provider hatasında mevcut
   güvenli ret kararını koru.
5. LLM tarafından kapsama alınan soruda zayıf deterministik planı SQL'e sözleşme
   olarak dayatma; mevcut schema-grounded LLM SQL üretimi ve doğrulamasını kullan.

## Etkilenen dosyalar

- `backend/app/prompts/schema_answerability.md`
- `backend/app/services/schema_answerability.py`
- `backend/app/agent/nodes/analyze_intent.py`
- `backend/app/agent/nodes/retrieve_context.py`
- `backend/app/agent/graph.py`
- `backend/tests/test_schema_reasoning_fallback.py`

API, veritabanı şeması, repository ve frontend değişmez.

## Başarı ölçütleri

- Tanınmayan fakat gerçek kolona bağlanabilen paraphrase SQL hattına girer.
- Hava durumu gibi alakasız soru kapsam dışında kalır.
- DELETE/UPDATE benzeri istekler LLM ikinci görüşüne gönderilmez.
- Uydurma kolon belirten LLM kararı reddedilir.
- SQL üretimi salt-okunur AST, object allowlist ve schema identifier
  doğrulamalarını kullanmaya devam eder.

## Doğrulama

```bash
cd backend
../.venv/bin/python -m pytest -q tests/test_schema_reasoning_fallback.py \
  tests/test_ag022_answerability.py tests/test_nlu_v2.py \
  tests/test_sql_schema_guard.py tests/test_deterministic_sql_pipeline.py
../.venv/bin/python -m pytest -q
```
