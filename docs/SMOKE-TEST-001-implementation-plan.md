# SMOKE-TEST-001 Implementation Plan

## Amaç

Çalışan ASM AI Agent backend'ini gerçek HTTP üzerinden değerlendiren, üretim iş
mantığından tamamen ayrık, tekrar çalıştırılabilir bir smoke-test runner sağlamak.

## Kapsam ve sınırlar

- Yalnızca `POST /api/v1/report/` kullanılacak.
- Senaryolar koddan ayrı JSON katalogda tutulacak.
- Üretim planner, value resolver, answerability, clarification, SQL builder,
  analytics, context, routing veya rapor üretim kodu değiştirilmeyecek.
- Patient-level row değerleri ve secret'lar artifact'lere yazılmayacak.
- Yeni runtime bağımlılığı eklenmeyecek.

## Uygulama adımları

1. On iki senaryolu, üç çok-turlu akış içeren typed JSON katalog oluştur.
2. HTTP transport, katalog parser, kanıt çıkarımı, assertion engine ve sonuç
   sınıflandırmasını `scripts/smoke_test_runner.py` içinde ayrık sorumluluklarla kur.
3. Timestamp geçmişi ve `latest` kopyasıyla JSON, CSV, Markdown ve standalone HTML
   artifact üretimini ekle.
4. Mocked HTTP unit testleriyle parsing, assertions, sessions, redaction, hata
   davranışı ve rendering'i doğrula.
5. Çalıştırma, genişletme, güvenlik ve bilinen API görünürlük sınırlarını belgele.

## Kabul ölçütleri

- CLI tam paket, toplantı preset'i ve filtreli çalışmayı destekler.
- Çok turlu akışta dönen canonical session ID yeniden kullanılır.
- PASS/PARTIAL/FAIL kuralları deterministiktir.
- Dört artifact hem tarihsel klasörde hem `latest` altında üretilir.
- Unit test paketi backend olmadan geçer.

