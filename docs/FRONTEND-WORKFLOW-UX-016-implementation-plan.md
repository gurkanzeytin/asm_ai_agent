# Frontend Workflow UX - Uygulama Planı

## Amaç

Med Agent yanıt akışını daha anlaşılır, SQL incelemesini daha verimli ve arayüz hareketlerini daha tutarlı hale getirmek.

## Kapsam

- LangGraph düğümlerinden gerçek workflow aşamalarını yayınlamak.
- NDJSON tabanlı, iptal edilebilir rapor akış endpoint'i eklemek.
- Frontend'de aşamaları mevcut parlak düşünme animasyonunda göstermek.
- Bağlantı, sorgu, sunucu ve geçersiz yanıt hatalarını ayrı sunmak.
- SQL tablo ve grafiklerini geniş bir diyalogda açmak.
- Panel, sohbet, yanıt ve tablo-grafik geçişlerinde ortak motion değerleri kullanmak.
- Backend ve frontend sözleşme testlerini güncellemek.

## Uyumluluk

Mevcut `/report/` endpoint'i korunur. Stream endpoint'i bulunmadığında frontend eski JSON çağrısına geri döner. Login ve mobil tasarım kapsam dışıdır.
