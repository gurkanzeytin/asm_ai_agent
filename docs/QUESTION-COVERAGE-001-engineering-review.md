# QUESTION-COVERAGE-001 Engineering Review

## Kapsam

Değişiklik semantik katalogları, cohort çözümleme adımını, offline audit aracını,
mentor soru paketini, testleri ve dokümantasyonu etkiler. API, database schema,
repository ve frontend değişmemiştir.

## Mimari uyum

- İş terimleri JSON kataloglarında tutuldu.
- Endpoint veya provider içine yeni business logic eklenmedi.
- SQL üretimi mevcut `QueryPlanner` -> `DeterministicSQLBuilder` -> `SQLValidator` hattında kalır.
- Yeni SQL şablonu veya doğrudan LLM çağrısı eklenmedi.
- Audit aracı uygulamanın mevcut analyzer/planner/builder/validator bileşenlerini
  yeniden kullanır; paralel bir iş mantığı hattı oluşturmaz.

## Güvenlik

- Kaynak görünüm whitelist'i değişmedi.
- PII kolonlarının selectable politikası değişmedi.
- Değişiklik yalnız aggregate/distribution sorgularını hedefler.
- Mentor paketinde ham hasta detayı isteyen soru bulunmaz.
- “Türk olmayan” ifadesi ancak tanımlı yabancı cohort'a çözüldüğünde negatif
  serbest metin filtresinden arındırılır; çözülmemiş genel negatif sorgular mevcut
  güvenlik davranışını korur.

## Risk değerlendirmesi

- `kanal` terimi bu görünümün iş alanında randevu kaynağını ifade ettiği varsayımıyla eşlendi. Canlı kullanıcı terminolojisinde farklı bir anlam taşıyorsa katalog terimi daraltılmalıdır.
- Tekil hasta eşanlamlıları “hasta” bağlamını içerir; genel “tekil sayı” ifadesi eklenmediği için doktor gibi başka varlıklarla çakışma riski sınırlandırıldı.
- `Uyruk <> N'Türkiye'` iş tanımı görünümdeki kategori değerinin tam olarak
  `Türkiye` olduğu varsayımına dayanır. Canlı DB smoke testinde NULL, farklı yazım
  ve kategori normalizasyonu doğrulanmalıdır.
- Golden audit'teki metadata drift uyarıları çalıştırma hatası sayılmaz. Golden
  veri bir few-shot/retrieval kataloğu olarak da kullanıldığı ve bazı beklenen
  metadata alanları eskidiği için bu farklar görünür uyarı olarak raporlanır.
- Doğal dil varyasyonları sonsuz olduğundan 243 deterministik soru mutlak kapsam
  garantisi değildir; ölçülebilir bir demo kapısı ve genişletilebilir regresyon
  tabanı sağlar.

## Sonraki inceleme kapısı

Sonraki dilimde kalan 6 cevaplanabilir fakat deterministik SQL üretilemeyen golden
şekil ve blind paketteki cohort, veri kalitesi ve dönem karşılaştırma açıkları
önceliklendirilmelidir. Expert ve acceptance paketlerinde sıfır gerileme şartı
korunmalıdır.

## Verification

- JSON katalogları `jq empty` ile doğrulandı.
- Değiştirilen test dosyası Ruff kontrolünden geçirilir.
- Tam backend test paketi ve expert/acceptance/blind evaluation paketleri çalıştırıldı.
- Tam backend sonucu: 2233 geçti, 1 atlandı.
- Mentor paketinin yalnız audit'ten geçen deterministik soru kimliklerini içerdiği
  otomatik testle doğrulandı.
- Canlı SQL Server bağlantısı kullanılmadı; gerçek kategori değerleri ve sonuç
  sözleşmesi için canlı ortam smoke testi hâlâ gereklidir.
