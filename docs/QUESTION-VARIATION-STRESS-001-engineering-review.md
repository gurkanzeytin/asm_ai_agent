# QUESTION-VARIATION-STRESS-001 Engineering Review

## Mimari uyum

- Araç yalnız katalog ve mevcut analyzer/planner/builder/validator bileşenlerini
  kullanır.
- LLM, network ve database bağlantısı açmaz.
- API route veya production iş akışı değişmez.
- Soru varyasyonları retrieval/few-shot veri kaynağına yazılmaz.
- Üretim deterministiktir; rastgele seed veya zamana bağlı cümle seçimi yoktur.

## Güvenlik

- PII/selectable=false kolonlar katalogdan otomatik bulunur.
- Ham listeleme probları erken clarification/out-of-scope veya güvenli
  deterministik projection bekler.
- Deterministik SQL oluşursa SELECT bölümünde korunan kolon aranır.
- SQL Validator bütün üretilen deterministic SQL'i AST/read-only kurallarıyla
  doğrular.
- Test sırasında gerçek hasta verisi veya kategori değeri kullanılmaz.

## Yarar

- Yeni bir metrik veya kolon eklendiğinde soru matrisi otomatik genişler.
- Tek tek cümle hardcode etmeden genel dil boşlukları ölçülür.
- Mentorun beklenmedik soru sorma riskine daha gerçekçi baseline sağlar.
- Başarısızlıkların yoğunluğu bir sonraki geliştirme sırasını sayısal belirler.

## Riskler ve sınırlamalar

- Şablonla üretilen sorular gerçek kullanıcı dilinin tamamını temsil etmez;
  gerçek üretim soruları ayrıca blind sete eklenmelidir.
- Bazı katalog metrik/boyut kombinasyonları teorik olarak uyumlu görünse de iş
  açısından anlamsız olabilir. Bu vakalar capability tasarımını gözden geçirmek
  için yararlı backlog'tur.
- Audit yalnız deterministik SQL yolunu ölçer; yeni schema-reasoning LLM fallback
  doğruluğu mock testler ve ileride canlı provider eval ile ayrıca ölçülmelidir.
- Capability probe cümleleri analitik sonuç sorusu değildir; burada amaç kolonun
  dil tanınmasıdır.

## İlk öncelik sırası

1. Şablon dışı gerçek kullanıcı ifadelerini ayrı blind sete eklemek.
2. Canlı provider ile schema-reasoning fallback doğruluğunu ölçmek.
3. Pazartesi gerçek kategori değerleriyle value grounding yapmak.
4. Yeni katalog öğelerinde 887/887 kapısını korumak.

## Verification

- 887 benzersiz `VAR-*` soru üretildi.
- 24 kolon ve 48 metrik tam kapsandı.
- Privacy guard probları korunan kolon kümesiyle eşleşti.
- Audit cache/reproducibility testi geçti.
- Başarı tabanı 650 minimumuyla korumaya alındı.
- Odaklı test sonucu: `5 passed`.
- Tam backend sonucu: `2270 passed, 1 skipped`.
- Ruff sonucu: `All checks passed`.
- Golden audit sonucu: 284 soruda 255 başarılı, 243 deterministik demo-ready.
