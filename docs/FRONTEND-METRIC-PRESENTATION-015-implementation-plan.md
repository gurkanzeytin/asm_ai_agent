# Implementation Plan

## Amaç

Temel göstergelerde teknik isimleri Türkçeleştirmek, değerleri birimleriyle sunmak ve sıfır ile veri yok durumlarını ayırmak.

## Uygulama

- Backend metrik kataloğundaki yaygın aliasları frontend sunum sözlüğüne ekle.
- Süre metriklerini dakika, randevu hacimlerini randevu birimiyle göster.
- Tam yüzdelerde gereksiz ondalık basamağı kaldır.
- Bilinen bir metrik `null` dönerse kartta `Veri yok` göster.
- Gerçek sayısal sıfırı normal değer olarak koru.
- Backend ve frontend `appointment_count` etiketini eşitle.
