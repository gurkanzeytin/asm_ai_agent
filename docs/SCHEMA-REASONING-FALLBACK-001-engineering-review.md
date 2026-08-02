# SCHEMA-REASONING-FALLBACK-001 Engineering Review

## Mimari uyum

- API route içine iş mantığı eklenmedi.
- LLM çağrısı provider interface üzerinden yapılır.
- Prompt Python içinde hardcode edilmez; prompt kaynağında tutulur.
- SQL üretimi mevcut `WorkflowService` ve `SQLService` hattında kalır.
- Database erişimi veya yeni bir repository yolu eklenmedi.

## Güvenlik sınırı

Schema reasoning yalnız kapsam sınıflandırması yapar ve SQL üretemez. Olumlu
karar aşağıdaki koşulların tamamını sağlamalıdır:

- `answerable` sonucu,
- en az 0.70 güven,
- en az bir destek kolonu,
- destek kolonlarının tamamının gerçek kolon kataloğunda bulunması,
- belirtilen metriklerin tamamının metrik kataloğunda bulunması.

Bu karar SQL çalıştırma izni değildir. Sonraki SQL ayrıca SELECT/CTE kök
kısıtına, mutasyon engeline, object allowlist'e ve schema identifier kontrolüne
tabidir.

## Riskler

- Ek LLM çağrısı yalnız bilinmeyen sorularda gecikme ve token maliyeti ekler.
- Bir LLM gerçek bir kolonu yanlış iş gerekçesiyle ilişkilendirip false-positive
  kapsam kararı verebilir. SQL doğrulaması güvenliği korur fakat semantik olarak
  yanlış analiz riskini tamamen sıfırlamaz.
- Fallback SQL için deterministik plan sözleşmesi kullanılmadığından sonuç
  metadata'sı ve çok turlu hafıza, katalogdan çözülen sorular kadar zengin
  olmayabilir.
- Provider erişilemiyorsa yeni kapsama davranışı devreye girmez ve eski güvenli
  ret sonucu korunur.

## Risk azaltma

- Fallback yalnız deterministic `no_domain_signal` sonucunda çağrılır.
- Açık güvenlik/kapsam-dışı ve ambiguity kararları override edilmez.
- Gerçek kolon kanıtı ve güven eşiği zorunludur.
- Yeni fallback soruları başarılı oldukça genel katalog eşanlamlısı veya metrik
  kuralına dönüştürülmeli; sık sorular sürekli LLM fallback'te bırakılmamalıdır.
- Üretimde `schema_reasoning` kararı, kolonlar, latency ve sonraki SQL outcome
  PII içermeden ölçülmelidir.

## Sonraki iyileştirme

LLM ikinci görüşünün yalnız kapsam değil, doğrulanabilir typed metric/dimension/
date planı üretmesi sonraki güvenli dilimdir. Bu, fallback yanıtlarının sonuç
sözleşmesini ve konuşma hafızasını güçlendirir; mevcut değişiklik bunu zorunlu
kılmadan erken ret problemini en küçük dilimde giderir.

## Verification

- Unknown paraphrase gerçek kolonla kabul edildi.
- Alakasız soru kapsam dışında kaldı.
- Unsafe write provider'a gönderilmedi.
- Hallucinated column kararı reddedildi.
- Weak deterministic plan schema-grounded LLM SQL yolu için kaldırıldı.
- İlgili answerability, routing, SQL schema guard ve deterministic pipeline
  regresyonları çalıştırıldı.
- Tam backend sonucu: 2239 geçti, 1 atlandı.
- Golden audit sonucu korunmuştur: 253 güvenli davranış, 243 deterministik
  demo-hazır soru.
