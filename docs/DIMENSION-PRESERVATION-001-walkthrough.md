# DIMENSION-PRESERVATION-001 Walkthrough

## Düzeltilen kullanıcı soruları

```text
Şube adı bazında farklı şubelerde tekrar eden hasta sayısını göster.
Bölüm adı raporlama bazında hasta ilk-son randevu gün farkını göster.
Randevu tipi bazında hasta ilk-son randevu gün farkını göster.
Hasta ilk-son randevu gün farkını randevu türü kırılımında göster.
```

Bu sorular artık istenen boyutu `QueryPlan.dimensions` içinde korur. Mevcut CTE
SQL üreticisi aynı boyutu hem hasta-seviyesi iç gruplamada hem sonuç-seviyesi dış
gruplamada kullanır.

## Özel metrik önceliği

“Farklı şubelerde tekrar eden hasta” ifadesi artık yalnız
`cross_branch_repeat_patient_count` metriğini seçer. Genel
`repeat_patient_count` aynı isteğe ikinci metrik olarak eklenmez; böylece güvenli
deterministik ilişki CTE'si kullanılabilir.

## İki dönem önkoşulu

`multi_period_patient_overlap_count` varyasyonları artık şu tip gerçek dönem
çiftleriyle üretilir:

- 2023 ve 2024
- 2024 ve 2025
- Mayıs 2024 ve Haziran 2024

## Ölçüm

| Ölçüm | Önce | Sonra |
|---|---:|---:|
| Başarılı varyasyon | 804 | 879 |
| Başarı oranı | %90,6 | %99,1 |
| Boyut uyuşmazlığı | 44 | 0 |
| Deterministik SQL yok | 33 | 0 |
| Metrik uyuşmazlığı | 2 | 0 |

Kalan sekiz vaka analitik veri sorusu değil, “bu kolonla hangi analizi
yapabilirsin?” biçimindeki meta-şema capability sorularıdır.

## Verification

- İlgili planner/catalog/varyasyon testleri: `180 passed`.
- Varyasyon testi: `9 passed`.
- Tam backend: `2261 passed, 1 skipped`.
- Golden audit: `255/284` başarılı, `243` deterministik demo-ready.
- Ruff: değiştirilen dosyalarda hata yok.
