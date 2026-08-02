# SCHEMA-CAPABILITY-001 Engineering Review

## Mimari uyum

- API route içinde iş mantığı yoktur.
- Kolon ve metrik bilgisi yalnız merkezi kataloglardan okunur.
- Endpoint doğrudan LLM çağırmaz; bu özellik hiç LLM çağırmaz.
- Database repository veya doğrudan bağlantı kullanılmaz.
- Mevcut `GeneratedReport` transport sözleşmesi korunur.

## Güvenlik

- PII veya `selectable=false` kolonlar ham değer kullanımını önermez.
- Doğrulanmamış (`requires_verified_mapping`) metrikler desteklenen metrikler
  listesine alınmaz.
- Doğrulanmış kategori değerleri yalnız PII olmayan kolonlarda gösterilir.
- Fiziksel kolon adı katalog dışından tahmin edilmez.

## Yanlış-pozitif koruması

- Yalnız “hangi analiz”, “ne işe yarar”, “açıkla/anlat” capability grameri
  değerlendirilir.
- Ayrıca alan/kolon/sütun belirteci veya fiziksel kolon adı gerekir.
- “2024 yılında bölüm bazında randevu sayısını göster” gibi analitik sorular
  capability yoluna girmez.

## Sınırlamalar

- 887/887, katalog-şablon tabanlı çevrimdışı kapsama sonucudur; sınırsız doğal
  dil veya canlı LLM doğruluk garantisi değildir.
- Kolon değer profilleri pazartesi canlı SQL Server kaynağından doğrulandıkça
  capability cevapları otomatik zenginleşecektir.

## Verification

- Tüm 24 kolon capability sorusu tipli cevap üretti.
- PII ve doğrulanmamış metrik testleri geçti.
- Graph kısa devresi SQL ve database sonucu oluşturmadan sonlandı.
- Tam regresyon: `2270 passed, 1 skipped`.
- Golden audit gerilemedi.
