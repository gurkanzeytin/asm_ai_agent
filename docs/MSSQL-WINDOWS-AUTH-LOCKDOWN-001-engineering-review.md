# MSSQL-WINDOWS-AUTH-LOCKDOWN-001 Engineering Review

## Review

The change keeps database policy in the configuration layer, before engine creation and before any repository can execute SQL. This matches the existing Clean Architecture boundary: API routes do not handle database credentials or query safety directly.

## Security Notes

- SQL authentication credentials are rejected even when provided through an explicit override URL.
- Windows Authentication cannot be disabled through `DB_TRUSTED_CONNECTION=false`.
- The allowed-object whitelist remains `dbo.vw_RandevuRaporu` by default.
- Query execution still goes through the repository layer and SQL validator.

## Test Coverage

Focused tests cover:

- Default allowed object configuration
- Constructed Windows-auth ODBC URL
- Rejection of non-MSSQL URLs
- Rejection of disabled Windows Authentication
- Rejection of username/password URL authority
- Rejection of SQL-auth query parameters
- Rejection of SQL-auth `odbc_connect` values

## Residual Risk

Live verification still depends on the Windows identity running the backend having read permission on `PusulaComed.dbo.vw_RandevuRaporu` and the Microsoft ODBC Driver 18 being installed on the host.
