# FRONTEND-HARDENING-002 Engineering Review

## Architecture

The route now coordinates layout only. Request and conversation behavior moved to `useChatController`, reducing route coupling and making state transitions testable. Backend report access remains isolated in the typed API client.

## Security And Privacy

Raw conversations and SQL rows are no longer persisted in browser storage. The direct vulnerable `xlsx` dependency was removed, and the production dependency audit reports no known vulnerabilities.

Authentication remains explicitly out of scope. The current application must not be treated as access-controlled until a backend identity and authorization contract exists.

## Data Integrity

The details panel now presents only values actually supplied by the current request state. Zod validation prevents malformed successful responses from reaching SQL and presentation code as trusted data.

## Residual Risk

- Conversation history is lost on refresh by design until a compliant server-side history service exists.
- The SQL results feature remains a large optional chunk because it includes virtualization and charting, but it no longer delays the initial route.
- Full lint has six existing Fast Refresh warnings in shared shadcn UI modules and no errors.
- Mobile layout and authentication were excluded by user direction.
