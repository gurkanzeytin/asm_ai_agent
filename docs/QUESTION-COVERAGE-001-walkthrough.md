# QUESTION-COVERAGE-001 Walkthrough

## Yapılan ilk dilim

Kullanıcıların resmi katalog terimleri yerine günlük dil kullanabildiği iki boşluk kapatıldı:

- “kanal”, “kanal kanal”, “kanala göre” ve “kanallara göre” ifadeleri randevu kaynağı boyutu `GenelRandevuKaynakAdi` ile eşlendi.
- “hasta tarafında tekil sayı” ve “hastalarda tekil sayı” ifadeleri `unique_patient_count` metriğiyle eşlendi.
- “Türk olmayan” ve “Türkiye dışındaki” ifadeleri yabancı uyruk cohort'una
  eşlendi. Grounding tamamlandıktan sonra eski serbest metin negatif filtresi
  kaldırıldığı için deterministik SQL güvenli biçimde üretilebiliyor.

Bu değişiklikler prompt veya Python içine iş kuralı eklemek yerine mevcut semantik JSON kataloglarında yapıldı. Böylece planner ve deterministik SQL builder mevcut güvenlik/uyum hattını aynen kullanır.

## Beklenen akış

`Kanal kanal randevu akışı nasıl?`

1. Boyut: `GenelRandevuKaynakAdi`
2. Metrik: `appointment_count`
3. Analiz: `distribution`
4. SQL kaynağı: deterministic

`Hasta tarafında tekil sayı kaç görünüyor?`

1. Boyut: yok
2. Metrik: `unique_patient_count`
3. Analiz: `distinct_count`
4. SQL kaynağı: deterministic

## Test kapısı

İki mevcut blind evaluation vakası `test_conversational_business_phrasing_regressions` ile doğrudan regresyon kapısına eklendi. Test, yalnız planın değil evaluation sözleşmesinin tamamının geçmesini ve SQL kaynağının deterministik olmasını ister.

Kullanıcının iki örnek sorusu da doğrudan regresyon testine alındı:

- `2024 yılının ortalama randevu süresi nedir?`
- `2024 yılında Türk olmayan uyrukların oranı nedir?`

İlk soru `AVG(CAST(RandevuSuresi AS FLOAT))` ve 2024 tarih sınırlarını,
ikinci soru `Uyruk <> N'Türkiye'` koşullu pay hesabını üretir. Her ikisi de
SQL Validator'dan geçer.

`golden_audit.py`, 284 soruluk bankayı aynı analyzer -> planner -> deterministic
builder -> validator hattında veritabanına bağlanmadan tarar. Bunun üzerinden
farklı analiz ailelerine dağıtılmış 60 soruluk `mentor_demo_pack.json` üretildi.
Soru grameri, söyleyiş varyasyonları, takip soruları ve kapsam dışı örnekler
`MENTOR-DEMO-QUESTION-BANK.md` içinde belgelendi.

## Doğrulama sonucu

- Yeni audit, cohort ve deterministik SQL odaklı testleri: 137 geçti.
- Tam backend paketi: 2233 geçti, 1 atlandı.
- Ruff ve JSON yapısal kontrolleri geçti.
- Expert SQL generation: 28/28.
- Acceptance SQL generation: 11/11.
- Blind SQL generation: 57/90 baseline'dan 59/90'a yükseldi.
- Golden bank audit: 284 sorudan 253 güvenli davranış, 243 deterministik
  demo-hazır soru.
