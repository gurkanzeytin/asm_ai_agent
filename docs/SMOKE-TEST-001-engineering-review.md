# SMOKE-TEST-001 Engineering Review

## Mimari değerlendirme

Runner üretim `backend/app` paketini import etmez. HTTP adapter, katalog parser,
assertion engine, evidence extraction ve artifact writer açık sorumluluk sınırlarına
sahiptir. Bu nedenle test sistemi üretim planner veya rapor davranışını değiştirmeden
API sözleşmesini dışarıdan gözlemler.

## Güvenlik değerlendirmesi

- Query row içerikleri sonuç modeline veya artifact'lere taşınmaz.
- İlk row için yalnızca alan adları tutulur.
- Hassas anahtarlar ve sık görülen inline secret biçimleri recursive redact edilir.
- HTTP client traceback'i redaction sonrasında saklanır.
- Runner header veya credential yapılandırması sunmaz ve bunları loglamaz.

## Test edilebilirlik

Transport protokolü mocked HTTP sonuçlarının enjekte edilmesini sağlar. Testler 12
senaryo parse'ını, 15 turu, assertion primitive'lerini, sınıflandırma matrisini,
session reuse'u, grouped session davranışını, row güvenliğini, redaction'ı, timeout ve
HTTP error sınıflandırmasını ve bütün artifact formatlarını kapsar.

## Bilinen sınırlar

Public API başarılı response'larda `sql_source` veya server-side stack trace sağlamak
zorunda değildir. Runner bu alanları `unavailable_fields` olarak açıkça işaretler;
tahmin etmez. Gerçek smoke sonuçları backend verisi, provider erişimi ve çalışma anı
performansına bağlıdır; mocked unit testler üretim backend sağlığının yerini tutmaz.

## Risk kararı

Değişiklik yalnızca yeni script, senaryo/test kataloğu ve dokümantasyon ekler. Üretim
workflow dosyalarına dokunulmadığı için davranış regresyonu riski düşüktür. En önemli
operasyonel risk, response sözleşmesi değiştiğinde assertion path'lerinin güncellenmesi
gereğidir; JSON katalog ve `unavailable_fields` raporu bu bakımı görünür kılar.
