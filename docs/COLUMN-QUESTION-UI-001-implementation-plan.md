# COLUMN-QUESTION-UI-001 — Implementation Plan

## Amaç

24 doğrulanmış kolonun her biri için ajanın anlayabileceği güvenli soru örnekleri üretmek; bu bilgiyi hem schema-reasoning/LLM bağlamına hem kolon açıklama yanıtlarına taşımak; açıklama, kapsam dışı, boş sonuç ve güvenli hata yollarında UI'nın tıklanabilir devam soruları göstermesini sağlamak.

## Değişiklik dilimleri

1. Kolon özellikleri ve doğrulanmış metriklerden güvenli örnek sorular üreten tek kaynak oluştur.
2. Örnekleri `SchemaKnowledge` üzerinden LLM schema bağlamına ekle.
3. “Bu sütunla hangi soruları sorabilirim?” soru ailesini kolon capability servisine ekle ve yanıtta örnekleri göster.
4. Workflow/API sözleşmesine geriye uyumlu `suggested_questions` alanı ekle.
5. Clarification, kapsam dışı, boş sonuç, yardım ve güvenli hata sonuçları için önerileri servis katmanında üret.
6. UI mesajlarında önerileri buton/chip olarak göster; tıklanınca aynı konuşmada gönder.
7. Boş sohbet ekranına sütun ailelerini temsil eden başlangıç soruları ekle.

## Güvenlik ve sınırlar

- PII kolonları için ham kişi listesi önerilmez; yalnız capability açıklaması veya güvenli toplulaştırma önerilir.
- Doğrulanmamış kategori değeri ya da `ProtokolIslemState` kod anlamı örneklere eklenmez.
- UI önerileri cevap yerine geçmez; yeni bir kullanıcı sorusu olarak mevcut planner, SQL validator ve read-only kapılardan geçer.
- Teknik çalışma hatasında veri veya sonuç uydurulmaz; güvenli yeniden deneme/alternatif sunulur.

## Etkilenecek yüzeyler

- `backend/app/semantics/question_examples.py`
- `backend/app/semantics/schema_knowledge.py`
- `backend/app/services/schema_capability.py`
- `backend/app/services/question_suggestions.py`
- Workflow/API DTO ve response mapping
- `frontend/src/lib/api.ts`
- `frontend/src/hooks/use-chat-controller.ts`
- `frontend/src/components/asm/{types,ChatMessage,EmptyState}.tsx`
- Türkçe UI sözlüğü ve backend/frontend testleri

## Doğrulama

- Her kolonun en az iki güvenli örneği olması
- Her kolon için “hangi soruları sorabilirim” capability cevabı
- API öneri sözleşmesi ve UI tıklama testi
- Backend tam regresyonu ve genişletilmiş varyasyon denetimi
- Frontend Vitest paketi ve üretim derlemesi

## Sonuç

Planın yedi değişiklik dilimi tamamlandı. Varyasyon matrisi 887'den 935'e
çıkarıldı; her 24 kolon üç farklı capability soru kalıbıyla denetleniyor.
