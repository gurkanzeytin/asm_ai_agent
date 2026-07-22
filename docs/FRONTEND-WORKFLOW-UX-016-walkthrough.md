# Frontend Workflow UX - Walkthrough

## Yanıt Akışı

Graph düğümü çalışmaya başlamadan önce request-scope callback üzerinden aşama yayınlanır. `/report/stream` bu olayları NDJSON satırları olarak iletir ve son satırda mevcut `ReportResponse` sözleşmesini döndürür.

Frontend aşama olaylarını aktif asistan mesajına yazar. Kullanıcı sırasıyla sorunun anlaşılması, SQL hazırlanması/doğrulanması/çalıştırılması, veri analizi ve rapor üretimini görür.

## Hatalar

API hata kodları dört kullanıcı görünümüne ayrılır: bağlantı, sorgu, sunucu ve geçersiz yanıt. Sorgu hataları yeniden deneme ile soru düzenleme aksiyonlarını; diğer hatalar yeniden denemeyi gösterir.

## SQL Geniş Görünüm

SQL araç çubuğundaki büyütme ikonu aynı sonucu tam ekran diyaloğa taşır. Arama, sütun yönetimi, filtreler, istatistikler, grafikler ve dışa aktarma kullanılmaya devam eder.

## Hareket Dili

Kısa geçiş süreleri ve easing değerleri `ui-motion.ts` içinde merkezileştirilmiştir. Sürekli dekoratif animasyon eklenmemiştir.
