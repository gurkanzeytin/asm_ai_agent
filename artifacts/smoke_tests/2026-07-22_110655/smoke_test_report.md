# ASM AI Agent Smoke-Test Raporu

- Oluşturulma: 2026-07-22T11:06:55+03:00
- Senaryo: 6
- Tur: 8
- Başarı oranı: %62.5
- PASS / PARTIAL / FAIL: 5 / 0 / 3
- Ortalama süre: 13.44 sn

## Sonuçlar

| Test | Kategori | Tur | Sonuç | Provider | Süre | Kritik sorun |
|---|---|---:|---|---|---:|---|
| 01_basic_distribution — Randevu Durumu Dağılımı | Dağılım | 1 | PASS | deterministic | 4.71 sn | - |
| 03_monthly_trend — Aylık Eğilim | Trend | 1 | FAIL | nvidia | 19.65 sn | - |
| 04_complex_multi_metric — Karma Çoklu Metrik | Karşılaştırma | 1 | PASS | nvidia | 23.87 sn | - |
| 05_grounded_branch — Doğrulanmış Şube | Filtre | 1 | FAIL | nvidia | 33.50 sn | Son 30 günlük doğru tarih aralığı bulunamadı. |
| 07_additive_followup — Eklemeli Takip Sorusu | Bağlam | 1 | PASS | deterministic | 4.71 sn | - |
| 07_additive_followup — Eklemeli Takip Sorusu | Bağlam | 2 | FAIL | static | 0.01 sn | Beklenen iş akışı sonucu alınmadı. |
| 09_year_only_followup — Yalnızca Yıl Takibi | Bağlam | 1 | PASS | deterministic | 11.01 sn | - |
| 09_year_only_followup — Yalnızca Yıl Takibi | Bağlam | 2 | PASS | deterministic | 10.03 sn | - |

## Kategori Dağılımı

- **Bağlam:** PASS 3, PARTIAL 0, FAIL 1
- **Dağılım:** PASS 1, PARTIAL 0, FAIL 0
- **Filtre:** PASS 0, PARTIAL 0, FAIL 1
- **Karşılaştırma:** PASS 1, PARTIAL 0, FAIL 0
- **Trend:** PASS 0, PARTIAL 0, FAIL 1

## Provider Kullanımı

- **deterministic:** 4 tur
- **nvidia:** 3 tur
- **static:** 1 tur

## En Yavaş Senaryolar

- 05_grounded_branch / tur 1: 33.50 sn
- 04_complex_multi_metric / tur 1: 23.87 sn
- 03_monthly_trend / tur 1: 19.65 sn
- 09_year_only_followup / tur 1: 11.01 sn
- 09_year_only_followup / tur 2: 10.03 sn

## Başarısız Assertion'lar

- **03_monthly_trend / tur 1 / MAJOR:** Provider veya model yönlendirmesi beklentiyle eşleşmiyor. (beklenen: `{"provider": "ollama|local_llm", "model_contains": "qwen"}`, gerçek: `{"providers": ["nvidia", "remote_llm", "insight_reuse"], "models": ["nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3-ultra-550b-a55b"]}`)
- **03_monthly_trend / tur 1 / MAJOR:** Aylık zaman kırılımı bekleniyor. (beklenen: `month`, gerçek: `None`)
- **05_grounded_branch / tur 1 / MAJOR:** Analiz tipi beklentiyle eşleşmiyor. (beklenen: `count|summary|list`, gerçek: `trend`)
- **05_grounded_branch / tur 1 / CRITICAL:** Son 30 günlük doğru tarih aralığı bulunamadı. (beklenen: `Son 30 günlük yarı-açık tarih aralığı`, gerçek: `SELECT TOP (100) 
    FORMAT(BaslangicTarihi, 'yyyy-MM-dd') AS Gun,
    COUNT(*) AS RandevuSayisi
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= '2026-06-23'
    AND BaslangicTarihi < DATEADD(day, 1, '2026-07-22')
    AND SubeAdi = 'TE…`)
- **07_additive_followup / tur 2 / CRITICAL:** Beklenen iş akışı sonucu alınmadı. (beklenen: `EXECUTE_SQL`, gerçek: `OUT_OF_SCOPE`)
- **07_additive_followup / tur 2 / MAJOR:** Analiz tipi beklentiyle eşleşmiyor. (beklenen: `comparison|distribution`, gerçek: `None`)
- **07_additive_followup / tur 2 / CRITICAL:** Bağlam uygulama kararı beklentiyle eşleşmiyor. (beklenen: `True`, gerçek: `False`)
- **07_additive_followup / tur 2 / CRITICAL:** SQL beklenen ifadeyi içermiyor: GROUP BY SubeAdi (beklenen: `contains GROUP BY SubeAdi`, gerçek: ``)

## SQL ve Oturum Kanıtları

### 01_basic_distribution / Tur 1

- Oturum: `0b5b3ea5-7c98-4e48-b621-ac9139366321`
- Bağlam uygulandı: `False`
- Devralınan alanlar: `-`
- Satır / sütun: `5` / `RandevuDurumu, appointment_count`

```sql
SELECT RandevuDurumu AS RandevuDurumu, COUNT(*) AS appointment_count
FROM dbo.vw_RandevuRaporu

GROUP BY RandevuDurumu
ORDER BY appointment_count DESC;
```

### 03_monthly_trend / Tur 1

- Oturum: `00c6bbec-a7db-4e7a-b226-98b0547d0c8c`
- Bağlam uygulandı: `False`
- Devralınan alanlar: `-`
- Satır / sütun: `7` / `period_start, monthly_appointment_count`

```sql
SELECT DATEFROMPARTS(YEAR(BaslangicTarihi), MONTH(BaslangicTarihi), 1) AS period_start, COUNT(*) AS monthly_appointment_count
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= '2026-01-22' AND BaslangicTarihi < DATEADD(day, 1, '2026-07-22')
GROUP BY DATEFROMPARTS(YEAR(BaslangicTarihi), MONTH(BaslangicTarihi), 1)
ORDER BY period_start ASC;
```

### 04_complex_multi_metric / Tur 1

- Oturum: `72a6244d-fa2b-44d9-865a-db2bcfb8b0f2`
- Bağlam uygulandı: `False`
- Devralınan alanlar: `-`
- Satır / sütun: `1` / `SubeAdi, appointment_duration_average, completed_appointment_rate, appointment_count`

```sql
SELECT SubeAdi AS SubeAdi, AVG(CAST(RandevuSuresi AS FLOAT)) AS appointment_duration_average, 100.0 * SUM(CASE WHEN RandevuDurumu = N'Gerçekleşti' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS completed_appointment_rate, COUNT(*) AS appointment_count
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= '2026-01-22' AND BaslangicTarihi < DATEADD(day, 1, '2026-07-22')

GROUP BY SubeAdi;
```

### 05_grounded_branch / Tur 1

- Oturum: `87ef2f0d-9e13-4394-ad1c-b2606542ab09`
- Bağlam uygulandı: `False`
- Devralınan alanlar: `-`
- Satır / sütun: `7` / `Gun, RandevuSayisi`

```sql
SELECT TOP (100) 
    FORMAT(BaslangicTarihi, 'yyyy-MM-dd') AS Gun,
    COUNT(*) AS RandevuSayisi
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= '2026-06-23'
    AND BaslangicTarihi < DATEADD(day, 1, '2026-07-22')
    AND SubeAdi = 'TEST ASM Gebze'
GROUP BY FORMAT(BaslangicTarihi, 'yyyy-MM-dd')
ORDER BY Gun;
```

### 07_additive_followup / Tur 1

- Oturum: `bc2ad888-68d0-4e9d-a4ab-4cdf43d9f5eb`
- Bağlam uygulandı: `False`
- Devralınan alanlar: `-`
- Satır / sütun: `1` / `SubeAdi, appointment_count`

```sql
SELECT SubeAdi AS SubeAdi, COUNT(*) AS appointment_count
FROM dbo.vw_RandevuRaporu

GROUP BY SubeAdi;
```

### 07_additive_followup / Tur 2

- Oturum: `bc2ad888-68d0-4e9d-a4ab-4cdf43d9f5eb`
- Bağlam uygulandı: `False`
- Devralınan alanlar: `-`
- Satır / sütun: `None` / `-`

```sql
-- SQL üretilmedi
```

### 09_year_only_followup / Tur 1

- Oturum: `e4c39117-6b22-4e0c-8420-24784994c250`
- Bağlam uygulandı: `False`
- Devralınan alanlar: `-`
- Satır / sütun: `1` / `OrtalamaRandevuSuresi`

```sql
SELECT TOP (100) AVG(CAST(RandevuSuresi AS FLOAT)) AS OrtalamaRandevuSuresi
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= '2025-01-01' AND BaslangicTarihi < DATEADD(day, 1, '2025-12-31')
```

### 09_year_only_followup / Tur 2

- Oturum: `e4c39117-6b22-4e0c-8420-24784994c250`
- Bağlam uygulandı: `True`
- Devralınan alanlar: `previous_question, entity_types, metrics, date`
- Satır / sütun: `1` / `OrtalamaRandevuSuresi`

```sql
SELECT TOP (100) AVG(CAST(RandevuSuresi AS FLOAT)) AS OrtalamaRandevuSuresi
FROM dbo.vw_RandevuRaporu
WHERE BaslangicTarihi >= '2024-01-01' AND BaslangicTarihi < DATEADD(day, 1, '2024-12-31')
```

## Yerelleştirme ve Risk Özeti

- Yerelleştirme/sunum bulgusu: 0
- Kritik başarısızlık: 4
- Major başarısızlık: 4
