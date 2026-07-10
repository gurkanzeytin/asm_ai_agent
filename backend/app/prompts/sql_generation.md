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
- Aggregation entity answers must SELECT the descriptive name and aggregate only.
- Prefer ad_soyad, bolum_adi, sirket_adi, test_adi, name, title, *_adi.
- Never SELECT id or *_id for user-facing aggregation unless explicitly asked.
- If counting by an ID, JOIN the entity table and GROUP BY id plus name, but
  keep only the name and aggregate in SELECT.
- Do not add WHERE filters that are not requested by the question.
