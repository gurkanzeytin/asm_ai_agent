# LIVE-CATEGORY-GROUNDING-001 — Implementation Plan

## Amaç

3 Ağustos 2026 canlı SQL Server doğrulamasından gelen kategori değerlerini
kanonik kolon kataloğuna ve LLM şema bağlamına taşımak; tam değer kümeleriyle
kısmi örnekleri ayırmak ve kaynak veri tekrarlarını otomatik eşanlamlı kabul
etmeden görünür kılmak.

## Değişiklikler

1. Kolon kataloğuna `known_values_complete`, `verified_distinct_count` ve
   `values_verified_at` metadata alanlarını ekle.
2. Randevu durumu, cinsiyet, randevu tipi ve uyruk profillerini canlı sonuçlarla
   güncelle.
3. `value_notes` bilgisini LLM şema kartında görünür yap.
4. Irak/Irak 2 belirsizliğini koruyan ve İngiliz eşleşmesinin kapsama sınırını
   belgeleyen regresyon testleri ekle.
5. Demo notuna doğrulanmış kategori tablosu ve veri kalitesi uyarıları ekle.

## Güvenlik

- Hasta adı, kimliği veya tekil satır katalog ya da dokümana yazılmaz.
- 149 uyruk değeri prompt içine gömülmez; değerler canlı `ValueCatalog`
  üzerinden çözülmeye devam eder.
- Kirli/mükerrer ülke adları otomatik birleştirilmez; belirsizlikte soru sorulur.

## Doğrulama

- Katalog metadata testleri
- Uyruk ambiguity/alias regresyon testleri
- Şema bilgisinin LLM render testi
- İlgili backend test paketi ve katalog doğrulaması
