# DIMENSION-PRESERVATION-001 Engineering Review

## Doğruluk

- Regex, boyut terimlerini `re.escape` ile işler; katalog terimi regex kodu gibi
  yorumlanmaz.
- Yalnız açık `bazında/göre/dağılım/kırılım` grameri boyutu korur.
- Çapraz-şube koşul boyutu, kullanıcı açıkça aynı boyutta sonuç kırılımı istemezse
  eskisi gibi gruplamadan çıkarılır.
- İki-dönem metriği SQL üretmeden önce iki tarih aralığı önkoşulunu taşır.

## Güvenlik

- SQL formülü ve SQL Validator değiştirilmedi.
- Yeni kolon veya serbest SQL parçası eklenmedi.
- Boyutlar mevcut katalog ve güvenli identifier kontrolünden geçmeye devam eder.
- PII projection stres probları ihlalsizdir.

## Sınırlamalar

- `GenelRandevuKaynakAdi` her zaman doktor değildir; pazartesi canlı değer profili
  görülmeden doktor etiketi olarak filtrelenmemelidir.
- 879/887 sonucu şablon tabanlı offline kapsama ölçümüdür, canlı LLM doğruluk
  garantisi değildir.
- Kalan capability soruları SQL üretmek yerine şema bilgisinden deterministik
  açıklama üretmelidir; bu ayrı bir özellik dilimidir.

## Verification

- Odaklı testler: `180 passed`.
- Tam regresyon: `2261 passed, 1 skipped`.
- Varyasyon: 887 soruda 879 başarılı; analitik metrik/boyut ve SQL-shape
  uyuşmazlığı sıfır.
- Golden audit gerilemedi: `255 passed`, `243 deterministic demo-ready`.
