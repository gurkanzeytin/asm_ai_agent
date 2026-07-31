# MSSQL-WINDOWS-AUTH-LOCKDOWN-001 Implementation Plan

## Goal

Enforce the production SQL Server contract:

- Server: `ASMPSHISBCK2`
- Database: `PusulaComed`
- Queryable object: `dbo.vw_RandevuRaporu`
- Authentication: Windows Authentication only

## Plan

1. Keep SQL Server settings centralized in `app.core.settings.Settings`.
2. Preserve the default database target and allowed-object whitelist.
3. Reject `DB_TRUSTED_CONNECTION=false` at startup.
4. Reject explicit `DATABASE_URL` values that include SQL usernames or passwords.
5. Reject explicit `DATABASE_URL` or `odbc_connect` values that disable Windows Authentication.
6. Cover the startup validation behavior with unit tests that do not open a database connection.

## Validation

Run the focused MSSQL support test module:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests\test_mssql_support.py -q
```
