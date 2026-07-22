# Frontend Workflow UX - Engineering Review

## Mimari

Progress callback bir `ContextVar` ile istek kapsamında tutulur; paylaşılan compiled graph üzerinde eşzamanlı istekler birbirine aşama sızdırmaz. API route yalnızca application stream event'lerini transport payload'una dönüştürür.

Normal rapor endpoint'i ve nihai response modeli değiştirilmedi. Frontend stream istemcisi 404 durumunda eski endpoint'e geri döner.

## Güvenilirlik

- Stream tamamlama ve hata olaylarından sonra kapanır.
- İstemci iptali backend görevini iptal eder.
- Eksik veya bozuk terminal payload yapılandırılmış geçersiz yanıt hatasına dönüşür.
- SQL geniş görünüm kendi içinde ikinci büyütme düğmesi üretmez.
- `prefers-reduced-motion` için mevcut global hareket azaltma kuralı geçerlidir.

## Riskler

Reverse proxy katmanı streaming response'ları buffer etmemelidir; endpoint `X-Accel-Buffering: no` başlığı gönderir. Platform seviyesinde ek buffering varsa aşamalar toplu görünebilir, ancak nihai yanıt etkilenmez.

## Test Kapsamı

Graph callback sırası, NDJSON progress/complete sözleşmesi, frontend stream ayrıştırma, hata kodu korunumu, aşama metni, hata aksiyonları ve geniş SQL diyaloğu test edilmiştir.
