# LLM-SCHEMA-KNOWLEDGE-001 Engineering Review

## Mimari uyum

- İş bilgisi mevcut semantik kataloglarda kalır; API route veya SQL endpoint'e
  business logic eklenmez.
- `SchemaKnowledge` birleştirici/read modeldir; ikinci kaynak oluşturmaz.
- LLM çağrıları provider katmanından yapılır.
- Prompt prompt kaynağında tutulur, Python içine gömülmez.
- Database erişimi repository dışına çıkarılmaz.
- SQL üretimi ve çalıştırılması mevcut WorkflowService/SQLService hattındadır.

## Güvenlik

- `HastaAdi` ve `HastaSoyadi` PII + selectable=false olarak LLM kartında görünür.
- Typed plan en fazla iki boyut, en fazla 100 satır limiti ve katalog kimliği
  doğrulaması uygular.
- Groupable=false kolon boyut olarak kabul edilmez.
- Zamansal olmayan kolon time column olamaz.
- Yazma istekleri schema reasoning'e ulaşmadan engellenmeye devam eder.
- `planning_source=llm_schema_reasoning`, deterministik SQL'i atlar fakat planı
  atlamaz: metric/date/dimension compliance, read-only AST, object allowlist ve
  schema identifier kontrolleri korunur.

## Faydalar

- Yeni Türkçe paraphrase'lerde kolon eşleme artar.
- LLM'in yakın fakat yanlış kolonu seçmesi azalır.
- Metrik formülleri ve tarih ekseni açık sözleşmeye dönüşür.
- Yanlış kategori değeri uydurma riski görünür value-grounding politikasıyla
  azalır.
- Şema değişiklikleri model fine-tuning gerektirmeden katalog güncellemesiyle
  uygulanabilir.

## Riskler ve bilinmeyenler

- Schema reasoning bilinmeyen sorularda bir LLM çağrısı ekler; latency ve token
  maliyeti yükselir.
- LLM gerçek kolonları semantik olarak yanlış ilişkilendirebilir. Typed doğrulama
  identifier güvenliğini sağlar fakat iş doğruluğu için evaluation zorunludur.
- Canlı DB distinct değerleri henüz alınmadığından birçok categorical kolon
  `live_db_required` durumundadır.
- Typed plan şu aşamada serbest kategorik filtre literalini taşımaz; bu filtreler
  mevcut ValueResolver veya SQL LLM tarafından ele alınır ve schema/value guard'a
  tabidir.
- Fine-tuning yapılmamıştır. Mevcut yaklaşım runtime grounding/RAG niteliğindedir
  ve bu şema boyutunda daha kolay güncellenebilir ilk tercihtir.

## Sonraki güvenli dilim

Canlı SQL Server'dan PII içermeyen categorical değerleri repository üzerinden
örnekleyip `value_catalog` cache'ine almak; LLM typed kararındaki değer
filtrelerini `ResolvedFilterPlan` olarak grounding sonrası plana eklemek. Ham
hasta adı/soyadı veya kimlik değerleri bu örneklemeye dahil edilmemelidir.

## Verification

- 24 kolon, 48 metrik ve relationship composition testi geçti.
- Doğrulanmış/kısmi/live-required value politikaları test edildi.
- Unknown paraphrase typed plana dönüştü.
- Önceki yıl ISO aralığı üretildi.
- Typed plan LLM SQL + plan compliance yolunu kullandı.
- Hallucinated column ve unsafe write regresyonları korundu.
- Tam backend sonucu: 2242 geçti, 1 atlandı.
- Golden audit gerilemedi: 253 güvenli davranış, 243 deterministik demo-hazır
  soru.
- Ruff ve JSON yapısal kontrolleri geçti.
