# FOLLOWUP-PRONOUN-VALUE-001 Walkthrough

The UI test found this chain:

1. `2025 yılında toplam kaç randevu alınmış?`
2. `Bunu randevu durumuna göre dağıtır mısın?`
3. `Sadece gerçekleşenleri göster.`
4. `Bunları bölümlere göre ilk 5 olacak şekilde sırala.`

The fourth turn treated `Bunları` as a possible department value because it
appeared immediately before the `bölümlere` dimension cue. The fix adds plural
demonstrative pronoun forms to the value extraction stopset, so the phrase is
handled as conversational context instead of a literal department name.

The regression is now covered at two levels:

- `extract_candidate_phrases()` returns no filter candidate for the plural
  pronoun plus dimension wording.
- The live-style chain keeps the 2025 date and `Gerçekleşti` status filter,
  then changes the grouping to department with `limit=5`.
