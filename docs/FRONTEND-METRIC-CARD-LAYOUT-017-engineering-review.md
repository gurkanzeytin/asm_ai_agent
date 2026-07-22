# Temel Gösterge Kart Düzeni - Engineering Review

## Dayanıklılık

- Sayı, yüzde, tarih, enum ve uzun kategori metinleri aynı kart geometrisinde kalır.
- `min-w-0`, `overflow-wrap:anywhere` ve iki satırlık clamp yatay taşmayı engeller.
- Sabit değer/etiket alanları aynı satırdaki kartların görsel hizasını korur.
- Ortak bağlamın tekilleştirilmesi tekrar eden uzun etiketleri kaldırır.

## Uyumluluk

`context` opsiyoneldir. Ham tek satırlı SQL metrik kartları ve eski kart üreticileri değişiklik gerektirmeden çalışır.

## Risk

İki satırı aşan içerik görsel olarak kısaltılır; veri kaybı yoktur ve tam metin `title` niteliğinde korunur.
