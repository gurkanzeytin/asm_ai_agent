# MSSQL-WINDOWS-AUTH-LOCKDOWN-001 Walkthrough

## Configuration Flow

The backend builds its SQLAlchemy URL from `DB_SERVER`, `DB_DATABASE`, and `DB_DRIVER` when `DATABASE_URL` is empty. The generated ODBC connection string includes `Trusted_Connection=yes`, so SQL Server authenticates the Windows identity running the backend process.

## Startup Guard

`Settings` now fails startup when:

- `DB_TRUSTED_CONNECTION=false`
- `DATABASE_URL` contains a username or password in the URL authority
- `DATABASE_URL` contains `UID`, `User`, `PWD`, or `Password` query parameters
- `DATABASE_URL` contains an `odbc_connect` string with `UID`, `User`, `PWD`, or `Password`
- `DATABASE_URL` explicitly sets `Trusted_Connection=no` or equivalent disabled integrated auth values

## Query Boundary

The SQL validator and schema inspector continue to enforce `DATABASE_ALLOWED_OBJECTS=dbo.vw_RandevuRaporu`, so generated SQL can read only from the approved view.

## Operational Check

Use `backend/scripts/verify_mssql_connection.py` to verify live access. It prints connection status, provider, allowed object, and metadata only; it does not print row data or connection secrets.
