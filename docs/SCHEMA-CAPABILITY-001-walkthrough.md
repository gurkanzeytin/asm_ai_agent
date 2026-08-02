# SCHEMA-CAPABILITY-001 Walkthrough

## Örnek davranış

Kullanıcı:

```text
Randevu başlangıç tarihi alanını kullanarak hangi analizi yapabilirsin?
```

Ajan SQL çalıştırmadan şunları açıklar:

- Fiziksel kolonun `BaslangicTarihi` olduğunu.
- Kolonun iş anlamını.
- Desteklenen tarih filtresi/trend işlemlerini.
- Bu kolona bağlı doğrulanmış metrikleri.
- İlişkili kolonları ve bilinen kullanım hatalarını.

PII örneği:

```text
Hasta adı alanını kullanarak hangi analizi yapabilirsin?
```

Cevap kolonun korumalı olduğunu, ham değerlerin, tekil kayıtların ve kişi
listelerinin gösterilmeyeceğini açıkça belirtir. SQL ve veritabanı çağrısı yapılmaz.

## Graph akışı

```text
AnalyzeIntent
  -> SchemaCapabilityService eşleşmesi
  -> GenerateSchemaCapabilityNode
  -> END
```

Normal analitik sorular bu grameri sağlamaz ve mevcut SQL akışına devam eder.

## Ölçüm

| Aile | Başarılı / toplam |
|---|---:|
| Metrik scalar | 285 / 285 |
| Metrik × boyut | 576 / 576 |
| Kolon capability | 24 / 24 |
| Privacy guard | 2 / 2 |
| **Toplam** | **887 / 887** |

## Verification

- Meta-şema + varyasyon testleri: `18 passed`.
- Graph/API/reporting odaklı testleri: `30 passed`.
- Tam backend: `2270 passed, 1 skipped`.
- Golden audit: `255/284` başarılı, `243` deterministik demo-ready.
- Ruff: değiştirilen dosyalarda hata yok.
