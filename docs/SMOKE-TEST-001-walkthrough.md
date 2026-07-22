# SMOKE-TEST-001 Walkthrough

## Akış

Runner katalog dosyasını parse eder, filtre/preset uygular ve her senaryo için bir
session başlatır. Her turda public report endpoint'ine `question` ve `session_id`
gönderir. Backend farklı bir canonical session ID döndürürse sonraki tur bunu kullanır.

Response önce secret redaction'dan geçirilir. Kanıt çıkarımı yalnızca outcome, SQL,
row metadata, aggregate KPI/analytics, provider/model, context, timing, error ve
izin verilen rapor metnini tutar. Query `rows` değerleri çıktı modeline alınmaz.

Beklentiler ortak assertion engine ile değerlendirilir. Bir critical veya iki major
hata senaryo turunu `FAIL`; tek major veya minor bulgu `PARTIAL`; diğer durumlar
`PASS` yapar. HTTP timeout ve HTTP hata response'ları critical failure'dır.

## Teslim edilen parçalar

- `scripts/smoke_test_runner.py`: CLI, transport, assertions, güvenli evidence ve
  artifact rendering.
- `tests/evaluation/smoke_scenarios.json`: 12 senaryo / 15 tur katalog.
- `tests/evaluation/test_smoke_test_runner.py`: backend gerektirmeyen unit testler.
- `docs/SMOKE_TEST_RUNNER.md`: operatör ve genişletme kılavuzu.

## Artifact inceleme

Terminal tablosu hızlı karar için tasarlanmıştır. Markdown raporu ayrıntılı assertion,
SQL ve session kanıtlarını; HTML raporu aynı bilgileri toplantıda kullanılabilir koyu
lacivert kartlarda gösterir. JSON otomasyon, CSV ise karşılaştırmalı analiz içindir.

