# DIMENSION-PRESERVATION-001 Implementation Plan

## Amaç

Özel hasta ilişki analizlerinde açıkça istenen şube, bölüm ve randevu tipi
kırılımlarının plandan düşmesini engellemek; stres üreticisindeki boyut ve dönem
önkoşulu yanlış-pozitiflerini temizlemek.

## Kök nedenler

1. Açık kırılım algısı “şube adı bazında” ve “bölüm adı raporlama bazında”
   ifadelerindeki ara etiket sözcüklerini kabul etmiyordu.
2. `RandevuTipiAdi` açık-kırılım terim kümesinde yoktu.
3. Özel çapraz-şube tekrar metriği ile genel tekrar-hasta metriği aynı anda
   seçilebiliyordu.
4. Stres üreticisi `doktor` alias'ını şablona sokunca beklenen kaynak boyutu
   `DoktorId` boyutuna dönüşüyordu.
5. İki-dönem hasta metriği sıfır veya tek dönem içeren sorularla sınanıyordu.

## Uygulama

- Açık-kırılım regex'i çok sözcüklü terimleri ve `adı/raporlama` niteleyicilerini
  güvenli biçimde destekleyecek.
- Randevu tipi/türü terimleri merkezi açık-kırılım eşlemesine eklenecek.
- Özel ilişki metriği, açık çoklu-metrik talebi yoksa genel tekrar metriğini
  bastıracak.
- Boyut varyasyonları grup cümlesi içinde kimliğini koruyan alias'lardan üretilecek.
- Doktor kimliği ile kaynak etiketi aynı çapraz eksen olarak üretilmeyecek.
- İki-dönem metriği yalnız iki açık tarih aralığıyla sınanacak.

## Etkilenen dosyalar

- `backend/app/planning/planner.py`
- `backend/app/semantics/catalog.py`
- `backend/tools/evaluation/question_variations.py`
- `backend/tests/test_agent_intelligence.py`
- `backend/tests/test_deterministic_sql_pipeline.py`
- `backend/tests/test_question_variation_audit.py`

## Rollout riski

Veritabanı veya API sözleşmesi değişmez. Yeni davranış yalnız açık GROUP BY
ifadelerini korur; “farklı şubelerde tekrar eden” gibi koşul sözcükleri tek başına
boyuta çevrilmez.
