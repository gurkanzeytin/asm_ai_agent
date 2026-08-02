# PROJECT-COVERAGE-AUDIT-001 — Walkthrough

## Uygulanan akış

1. Repository giriş noktaları, servis sınırları, semantik kataloglar, planlayıcı, deterministik SQL üretici, sonuç sözleşmeleri, değerlendirme araçları ve test yüzeyi incelendi.
2. 233 vakalık genel SQL-generation paketi çalıştırıldı; ham 31 başarısızlık gerçek ürün açığı, kontrollü sınırlama ve eski test beklentisi olarak sınıflandırıldı.
3. Tek soruya özel SQL eklemek yerine genel ifade aileleri ve plan bileşim kuralları geliştirildi.
4. Yeni davranışlar `test_project_coverage_audit.py` ile karakterize edildi.
5. Değerlendirme beklentileri güncel ürün sözleşmesiyle hizalandı; cevaplanamaz soruda neden + alternatif başarı sayıldı.
6. Repo haritası ve genel risk raporu güncellendi.

## Örnek davranışlar

| Soru ailesi | Plan/çıktı |
|---|---|
| “24 saat kala alınanların durumu” | `cohort_analysis`, doğrulanmış beş durumun sayı/oranları |
| “Geç alınanlar bölümlerde nasıl?” | Boyutlu kohort SQL'i, bölüm ayrıştırma + GROUP BY |
| “Tarih aralığı bozuk kayıtları say” | `invalid_date_range_count` |
| “Süre tarih farkıyla tutmuyor mu?” | `duration_mismatch_count` |
| “Kaynak ve durum kırılımı” | İki boyutlu `cross_analysis` |
| “2024 günlük ortalama” | Tek scalar `average` |
| “Günlük ortalama trendi” | Gün kırılımlı `time_trend` |
| “Son zamanlarda durumumuz nasıl?” | Dört KPI'lı deterministik dönem karşılaştırması |
| “Doktor maaşlarını sırala” | Kontrollü sınırlama + cevaplanabilir alternatif |

## Doğrulama

- `cd backend && ../.venv/bin/pytest -q` → 2413 passed, 1 skipped
- Genel evaluation → 233/233
- Question variations → 887/887
- Root smoke → 40/40
- Değişen Python dosyaları Ruff → temiz
- Frontend test/build → bağımlılıklar eksik olduğu için başlamadı
