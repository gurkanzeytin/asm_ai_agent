# SCHEMA-REASONING-FALLBACK-001 Walkthrough

## Yeni çalışma akışı

Örnek tanınmayan soru:

```text
Geçen seneki görüşmeler ne kadar vakit almış?
```

1. Mevcut deterministic analyzer bilinen entity/metric söyleyişi bulamaz ve
   `no_domain_signal` üretir.
2. `SchemaAnswerabilityService`, soruyu kolon ve metrik kataloğuyla birlikte
   LLM provider katmanına gönderir.
3. LLM yalnız yapılandırılmış kapsam kararı verir; SQL üretmez.
4. Karar `RandevuSuresi` gibi gerçek bir destek kolonuna dayanıyor ve güven
   eşiğini geçiyorsa graph soruyu database pipeline'a alır.
5. Deterministik planner bu söyleyişi zaten çözemediği için onun boş/tahmini
   planı serbest bırakılır.
6. Mevcut SQL prompt'u gerçek şema bağlamıyla LLM SQL üretimini yapar.
7. SQL; parser, salt-okunur AST, object whitelist, schema identifier ve mevcut
   güvenlik doğrulamalarından geçmeden çalıştırılmaz.
8. Sorgu sonucu mevcut analytics/report hattında Türkçe cevaba dönüştürülür.

## Değişmeyen erken engeller

- Veri ekleme, silme, güncelleme ve şema değiştirme istekleri.
- Katalogda açıkça bulunmadığı tanımlanan ödeme, reçete, tanı, adres gibi
  kavramlar.
- Mevcut ambiguity kurallarının hedefli açıklama gerektirdiği sorular.

Bu üç grup schema-reasoning fallback'e ulaşmaz.

## Kontrollü başarısızlık

Provider kapalıysa, timeout oluşursa, JSON bozuksa, karar düşük güvenliyse veya
LLM `DolulukOrani` gibi olmayan bir kolon/metrik uydurursa fallback kararı kabul
edilmez. Sistem eski güvenli kapsam davranışını korur; güvenlik için fail-open
yapmaz.

## Doğrulama sonucu

- Yeni ve ilişkili regresyon paketi: 189 test geçti.
- Tam backend paketi: 2239 test geçti, 1 test atlandı.
- Ruff: geçti.
- Golden audit değişmedi: 284 soruda 253 güvenli davranış ve 243
  deterministik demo-hazır soru.
- Canlı SQL Server kullanılmadı; canlı kategori ve sonuç doğrulaması ayrı smoke
  test gerektirir.
