# SQL Generation Template

You are tasked with generating a PostgreSQL SQL query based on a user question and a provided database schema.

## Parameters
- **Database Dialect**: {dialect}
- **Current Date**: {current_date}
- **Schema Context**:
{schema}

## User Question
{question}

## Instructions
1. Write syntactically valid SQL targeting the {dialect} dialect.
2. Return ONLY the raw SQL query. Do not explain. Do not reason. Do not wrap SQL in markdown code blocks.

---

## Examples

### GOOD OUTPUT
SELECT d.name, COUNT(a.id) AS appointment_count
FROM doctors d
JOIN appointments a ON d.id = a.doctor_id
GROUP BY d.name
ORDER BY appointment_count DESC
LIMIT 1;

---

### BAD OUTPUT
Here is the SQL query:
SELECT d.name, COUNT(a.id) AS appointment_count FROM doctors d JOIN appointments a ON d.id = a.doctor_id GROUP BY d.name ORDER BY appointment_count DESC LIMIT 1;
(Reason: explanatory text preceding the query is not allowed)

---

### BAD OUTPUT
```sql
SELECT d.name, COUNT(a.id) AS appointment_count FROM doctors d JOIN appointments a ON d.id = a.doctor_id GROUP BY d.name ORDER BY appointment_count DESC LIMIT 1;
```
(Reason: markdown code fences are not allowed)

---

### BAD OUTPUT
To answer this question we first need to join doctors with appointments on doctor_id.
SELECT d.name, COUNT(a.id) AS appointment_count FROM doctors d JOIN appointments a ON d.id = a.doctor_id GROUP BY d.name ORDER BY appointment_count DESC LIMIT 1;
(Reason: reasoning or steps preceding the query are not allowed)

---

### BAD OUTPUT
SELECT d.name, COUNT(a.id) AS appointment_count FROM doctors d JOIN appointments a ON d.id = a.doctor_id GROUP BY d.name ORDER BY appointment_count DESC LIMIT 1;
Hope this helps!
(Reason: conversational text following the query is not allowed)

---

## FINAL REQUIREMENTS
- Return exactly one executable SQL statement.
- Begin with SELECT (or WITH when using a CTE).
- End with a semicolon.
- Do not explain.
- Do not reason.
- Do not apologize.
- Do not use markdown.
- Do not include code fences.
- Do not include comments.
- Output only SQL.
