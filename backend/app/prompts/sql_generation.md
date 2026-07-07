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
2. Return ONLY the raw SQL query inside a markdown block. No conversational text.
