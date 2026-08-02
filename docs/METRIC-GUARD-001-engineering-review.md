# METRIC-GUARD-001 Engineering Review

## Doğruluk

- Display name eşleşmesi yalnız synonym eşleşmediğinde devreye girer; mevcut
  metrik önceliği ve çoklu-metrik sırası korunur.
- Sabit-boyut eşdeğerliği sadece aynı `COUNT(*)`, `appointment_count` ve zorunlu
  fixed dimension birlikte mevcutsa kabul edilir.
- Doğrulanmamış metrikler normal planlamaya ve LLM SQL üretimine geçirilmez.

## Güvenlik

- Bilinmeyen durum kodu veya kolon ilişkisi tahmin edilmez.
- SQL Validator ve salt-okunur politika değişmemiştir.
- Hasta adı/soyadı gibi PII kolonlarına ilişkin stres kontrolleri geçmeye devam
  etmektedir.

## Riskler

- Clarification, kullanıcıya doğrudan sonuç vermekten daha sınırlıdır; fakat
  yanlış iş kuralıyla kesin sayı vermekten güvenlidir.
- `HastaId`/`HastaId2` ve `ProtokolIslemState` anlamları canlı sistem sahibinden
  doğrulanmadan bu metrikler etkinleştirilmemelidir.
- Kalan 83 stres vakasının tamamı aynı önemde değildir; sentetik boyut
  çakışmaları ile gerçek SQL şekli eksikleri ayrı incelenmelidir.

## Verification

- Odaklı ajan zekâsı + varyasyon testleri: `128 passed`.
- Varyasyon regresyonu: `7 passed`.
- Tam backend: `2253 passed, 1 skipped`.
- Ruff: değiştirilen dosyalarda hata yok.
- JSON doğrulaması: iki güncellenen golden kaynak geçerli.
- Golden audit: `255/284` başarılı, `243` deterministik demo-ready.
