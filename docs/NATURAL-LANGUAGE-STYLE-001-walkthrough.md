# NATURAL-LANGUAGE-STYLE-001 Walkthrough

The language layer now has two complementary controls.

Prompt-driven responses receive explicit style rules: write in natural Turkish, answer directly, avoid internal identifiers, and avoid mechanical phrases such as "Sorgu sonucu", "listelenmiştir", and "tespit edilmiştir" unless the wording is necessary.

Deterministic responses use friendlier copy before the LLM is involved. Single-value answers now render as `# Yanıt` with a sentence such as `2025 yılında toplam **213.855** randevu alınmış.` Tables render under `# Sonuçlar` and use `kayıt bulundu` / `randevu durumu bulundu` wording. Empty results now say the criteria did not match records without emphasizing the internal query execution.

Clarification fallback text is Turkish as well, so unrecognized ambiguity no longer falls back to English.
