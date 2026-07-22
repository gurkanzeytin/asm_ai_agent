# Implementation Plan

## Amaç

Logo SVG içindeki gömülü PNG katmanlarının opak siyah arka planını kaldırmak.

## Uygulama

- SVG içindeki tüm PNG veri katmanlarını tespit et.
- Siyah pikselleri şeffaf alfa kanalına dönüştür.
- Antialias kenarlarını alfa oranına göre yeniden hesaplayarak siyah saçakları önle.
- İşlenmiş PNG verilerini aynı SVG içine geri yerleştir.
- Şeffaf köşe piksellerini otomatik asset testiyle doğrula.
