# COLUMN-QUESTION-UI-001 — Walkthrough

## Kullanıcı deneyimi

Boş sohbet ekranı artık altı farklı soru ailesini gösterir: tek ve çoklu
kırılım, ortalama, oran, dönem karşılaştırması ve randevu davranışı. Bir örneğe
tıklamak soruyu normal sohbet akışıyla gönderir.

Kullanıcı bir sütunun kapasitesini doğrudan da sorabilir:

```text
Randevu süresi sütunuyla hangi soruları sorabilirim?
```

Ajan SQL çalıştırmadan sütunun anlamını, desteklenen işlemleri, güvenlik
sınırlarını ve tıklanabilir örnek soruları döndürür. Aynı davranış katalogdaki
24 sütunun tamamında geçerlidir.

## Kontrollü devam akışı

```text
Kullanıcı sorusu
  -> cevap veya kontrollü sonuç
  -> suggested_questions
  -> UI soru düğmeleri
  -> aynı güvenli planner + SQL validator akışı
```

- Belirsiz soruda seçenekler doğrudan tıklanabilir yanıta dönüşür.
- Sütun yardımında o sütuna özel örnekler gösterilir.
- Kapsam dışı, boş sonuç ve güvenli hata halinde katalogdan türetilen alternatifler sunulur.
- Ağ/API hatasında UI kendi güvenli başlangıç sorularını gösterir.

## LLM bilgi genişlemesi

`SchemaKnowledge` içindeki her kolon kartı artık doğal dil örneklerini de taşır.
Bu bir model fine-tune işlemi değildir; LLM'in her istekte kullandığı güncel,
doğrulanmış şema bağlamının zenginleştirilmesidir. Yeni kolon veya yetenek
eklendiğinde örnekler aynı katalog özelliklerinden türetilir.

## Doğrulama

- Genişletilmiş soru matrisi: `935/935` başarılı, `812` deterministik SQL vakası.
- Tam backend: `2419 passed, 1 skipped`.
- Tam frontend: `139 passed`.
- Frontend üretim derlemesi: başarılı.
