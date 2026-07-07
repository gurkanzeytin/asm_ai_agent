# AI Development Rules

## General

- Follow Clean Architecture.
- Never introduce business logic into API routes.
- Never duplicate code.
- Prefer composition over inheritance where appropriate.
- Keep functions focused on a single responsibility.

## Database

- Never access the database directly from API routes.
- Use the repository layer.

## AI

- Never call the LLM directly from endpoints.
- All LLM interactions go through the provider layer.

## Prompt Management

- Prompts are stored only under `/prompts`.
- Never hardcode prompts in Python files.

## SQL Safety

- Every generated SQL query must pass the SQL Validator.
- Only read-only queries are allowed.

## Testing

- Every new feature must include or update tests.

## Documentation

- Every feature must produce:
  - Implementation Plan
  - Walkthrough
  - Engineering Review