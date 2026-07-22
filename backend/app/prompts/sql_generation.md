Generate one executable {dialect} SQL query.

Current date: {current_date}

Schema:
{schema}

Question:
{question}

Output rules:
- Return raw SQL only.
- Begin with SELECT or WITH.
- End with semicolon.
- No markdown, comments, explanation, or extra text.
- Use only objects and columns listed in Schema, spelled exactly as listed.
  Never invent identifiers.
- Copy filter values from the question into string literals exactly as written.
  Never fix spelling or add diacritics.
- Aggregation entity answers must SELECT the descriptive name and aggregate only.
- Prefer descriptive name columns (GenelRandevuBolumAdi, HizmetAdi, SubeAdi,
  RandevuTipiAdi, RandevuDurumu, KategoriAdi) over Id columns.
- Never SELECT Id columns for user-facing aggregation unless explicitly asked.
- Do not add WHERE filters that are not requested by the question.
- Period analysis/trend questions (analiz, trend, egilim) must return monthly
  aggregation, never raw rows: group rows by a year-month bucket and order by it.
{dialect_rules}
