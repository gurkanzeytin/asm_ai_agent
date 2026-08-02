# QUESTION-COVERAGE-001 Implementation Plan

## Amaç

`dbo.vw_RandevuRaporu` ile cevaplanabilen gerçek kullanıcı sorularında doğru intent, metrik, boyut, dönem ve SQL üretme oranını artırmak; kapsam dışı sorularda güvenli ve açıklayıcı cevap vermek.

## Mevcut baseline

- 24 kolonluk doğrulanmış görünüm kataloğu.
- 48 metrik ve 22 ilişki tanımı.
- 284 golden soru, 118 evaluation vakası, 78 kolon kapsama vakası ve 12 çok turlu senaryo.
- Expert SQL generation: 28/28.
- Acceptance SQL generation: 11/11.
- Blind SQL generation: 57/90; 33 başarısız vaka.
- Blind failure yoğunluğu: plan-not-answerable 16, gereksiz clarification 15, yanlış analiz tipi 13, sonuç sözleşmesi 12, yanlış metrik 10.

İlk uygulama dilimi sonunda blind sonuç 59/90'a çıktı. Ayrıca 284 golden
sorunun tamamını veritabanına bağlanmadan denetleyen audit aracı 253 güvenli
davranış ve 243 deterministik demo-hazır soru tespit etti.

## Aşamalı plan

### Faz 1 — Gerçek dil kapsaması

1. Başarısız blind vakaları `routing`, `metric`, `dimension`, `time`, `cohort`, `contract` ve `out-of-scope` sınıflarına ayır.
2. Her düzeltmede tek bir genellenebilir dil kuralı ekle; vaka cümlesine özel hardcode kullanma.
3. Düzeltilen her blind vakayı CI'da çalışan odaklı regresyon testine dönüştür.
4. İlk dilim:
   - “kanal” -> `GenelRandevuKaynakAdi` boyutu,
   - “hasta tarafında tekil sayı” -> `unique_patient_count` metriği.
5. Mentor demosu için farklı analiz ailelerinden seçilmiş 60 doğrulanmış soruyu
   ayrı bir paket olarak yayımla.
6. “Türk olmayan” ve “Türkiye dışındaki” söyleyişlerini yabancı uyruk cohort'una
   eşle; doğal dildeki negatif ipucunu grounding sonrasında SQL'i engellemeyecek
   şekilde temizle.

### Faz 2 — Veri kalitesi ve cohort dili

1. `missing_department_count`, `invalid_date_range_count`, `duration_mismatch_count` için günlük kullanıcı söyleyişlerini genişlet.
2. “son dakika”, “24 saat kala”, “acele”, “geç alınan” ifadelerini tek cohort resolver altında standardize et.
3. Cohort + bölüm/şube kırılımlarını deterministik SQL ve result contract ile kapat.

### Faz 3 — Dönem ve performans soruları

1. Boyutlu dönem karşılaştırmalarında `period_comparison` önceliğini variance/ranking sinyallerinin önüne al.
2. `adaptive_time_comparison` ve `multi_metric_performance` için tekil sonuç sözleşmelerini netleştir.
3. “parlamış”, “iyi gidiyor”, “fark var mı” gibi göreli performans ifadelerini ölçülebilir metrik ve dönem varsayımlarıyla cevapla; kullanılan varsayımı response metadata'da göster.

### Faz 4 — Canlı veri doğruluğu

1. Üretimden kimliksizleştirilmiş gerçek soru örnekleri topla.
2. Planner-only ve SQL-generation kapılarından sonra live DB result-contract testi çalıştır.
3. Sıfır sonuç, düşük örneklem, NULL yoğunluğu ve beklenmeyen kategori değerlerini ayrı başarısızlık sınıfları olarak raporla.
4. Kullanıcıya sunulan cevabın SQL sonucu dışına taşmadığını doğrula.

### Faz 5 — Sürekli iyileştirme

1. Her kullanıcı sorusunu ham PII olmadan `resolved intent`, `metric`, `dimension`, `outcome`, `latency`, `failure code` ile ölç.
2. En sık başarısız ilk 10 söyleyişi haftalık evaluation backlog'una al.
3. Blind başarı oranı için kademeli CI eşiği uygula; önce desteklenen/answerable vakaları ayrı ölç.

## Etkilenen alanlar

- `backend/app/resources/column_intelligence.json`
- `backend/app/resources/metric_catalog.json`
- `backend/app/resources/domain_synonyms.json`
- `backend/app/services/query_analyzer.py`
- `backend/app/planning/planner.py`
- `backend/app/services/deterministic_sql_builder.py`
- `backend/app/analytics/result_contracts.py`
- `backend/app/resources/evaluation_cases.json`
- `backend/app/resources/view_semantics.json`
- `backend/app/resources/mentor_demo_pack.json`
- `backend/tools/evaluation/golden_audit.py`
- `backend/tests/test_golden_question_audit.py`
- `backend/tests/test_evaluation_harness.py`

API sözleşmesinde veya veritabanı şemasında ilk faz için değişiklik gerekmez.

## Rollout ve riskler

- Geniş ve bağlamsız eşanlamlılar yanlış pozitif üretebilir; terimler ilgili iş varlığıyla sınırlandırılmalıdır.
- Blind dataset cümlesini birebir hardcode etmek gerçek genelleme sağlamaz; her değişiklik yakın paraphrase testleriyle desteklenmelidir.
- Yeni deterministik kabiliyet SQL Validator ve Plan Compliance kontrollerini atlamamalıdır.
- Canlı DB testi yalnız salt-okunur whitelist içindeki görünümde çalışmalıdır.

## Başarı ölçütleri

- Expert ve acceptance paketlerinde gerileme olmaması.
- İlk dilimde BLIND-CAS-006 ve BLIND-CAS-008'in deterministik olarak geçmesi.
- Answerable blind vakalarının başarı oranının her dilimde ölçülmesi.
- Kapsam dışı soruların SQL üretmeden güvenli yönlendirme vermesi.
- Mentor paketindeki her sorunun audit sırasında deterministik SQL üretmesi ve
  SQL Validator'dan geçmesi.
