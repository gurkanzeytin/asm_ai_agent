# PROJECT-COVERAGE-AUDIT-001 — Implementation Plan

## Amaç

SQL Server randevu görünümündeki doğrulanmış alanlarla ilgili doğal dil sorularında ajanın cevap üretme oranını yükseltmek; tek bir örnek soruya özel kurallar yerine aynı anlam ailesindeki ifadeleri genel planlara dönüştürmek.

## Denetim kapsamı

- Soru analizi, semantik kataloglar ve plan üretimi
- Deterministik SQL üretimi, SQL doğrulama ve sonuç sözleşmeleri
- İki/üç bileşenli sorular, kohortlar, veri kalitesi ve dönem karşılaştırmaları
- Değerlendirme paketleri, testler, çalışma/deploy dokümantasyonu

## Bu dilimde yapılacak en küçük güvenli değişiklikler

1. Son dakika/24 saat kala/geç veya acele alınan randevu ifadelerini mevcut doğrulanmış `lead_time_under_24h` kohortuna bağla.
2. Geçersiz tarih aralığı ve süre-tarih farkı tutarsızlığı için genel ifade ailesini genişlet.
3. “Kaynak ve durum kırılımı” gibi iki boyutlu sorularda durum boyutunu güvenilir biçimde yakala.
4. Boyutla gruplanan sayısal veri-kalitesi sonuçlarını `DistributionResult` sözleşmesine taşı.
5. Formülü kendi içinde günlük ortalama hesaplayan metrikleri trend serisinden ayır.
6. Çok metrikli performans özetlerini LLM'e bırakmadan dönem karşılaştırma SQL'iyle üret.
7. Görünümde bulunmayan maaş bilgisini kontrollü sınırlama ve mevcut alternatiflerle karşıla.

## Etkilenecek yüzeyler

- `backend/app/semantics/reasoning.py`
- `backend/app/resources/analysis_patterns.json`
- `backend/app/resources/metric_catalog.json`
- `backend/app/resources/column_intelligence.json`
- `backend/app/planning/planner.py`
- `backend/app/services/deterministic_sql_builder.py`
- İlgili backend regresyon testleri
- `docs/repo-map.md` ve denetim raporları

## Varsayımlar ve sınırlar

- “Geç/acele/24 saat kala alınan randevu” bu görünümde `CreatedDate` ile `BaslangicTarihi` arasındaki 0–24 saat olarak yorumlanır ve cevapta varsayım olarak gösterilir.
- İptal, maaş ve görünümde olmayan diğer alanlar uydurulmaz; ajan nedenini ve cevaplanabilir alternatifi söyler.
- Canlı SQL Server değer keşfi ve son UI turu, kullanıcının diğer bilgisayara erişeceği pazartesi yapılacaktır.
- Doğrulanmamış `ProtokolIslemState` kod anlamları kullanılmayacaktır.

## Doğrulama

- Hedefli planlayıcı ve deterministik SQL testleri
- Tüm backend test paketi
- Ruff kalite kontrolü
- 887 soru varyasyonu ve değerlendirme paketleri
- Pazartesi canlı SQL Server + UI duman testi
