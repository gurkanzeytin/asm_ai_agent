"""Safe database connection verification script.

Opens a connection using the application's configured engine, runs
'SELECT 1' and a bounded read against the first allowed view/object.
Prints connection status, provider, database name, view accessibility,
column names, and row count. Never prints row data or connection secrets.

Usage (from the backend directory):
    python scripts/verify_mssql_connection.py
"""

import asyncio
import sys
from pathlib import Path

# Add backend directory to sys.path to resolve 'app' correctly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.database.session import engine  # noqa: E402


def _provider() -> str:
    url = settings.DATABASE_URL or ""
    if url.startswith("mssql"):
        return "mssql"
    if url.startswith("postgresql") or url.startswith("postgres"):
        return "postgresql"
    if url.startswith("sqlite"):
        return "sqlite"
    return "unknown"


def _view_test_sql(provider: str, object_name: str) -> str:
    if provider == "mssql":
        return f"SELECT TOP (5) * FROM {object_name};"
    return f"SELECT * FROM {object_name} LIMIT 5;"


async def main() -> int:
    provider = _provider()
    print("===== DATABASE CONNECTION VERIFICATION =====")
    print(f"Detected provider  : {provider}")
    print(f"SQL dialect        : {settings.SQL_DIALECT}")
    print(f"Configured schema  : {settings.DATABASE_SCHEMA}")
    print(f"Allowed objects    : {', '.join(settings.DATABASE_ALLOWED_OBJECTS) or '(unrestricted)'}")

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1 AS connection_test;"))
            value = result.scalar()
            print(f"Connection test    : OK (SELECT 1 -> {value})")

            if provider == "mssql":
                db_name = (await conn.execute(text("SELECT DB_NAME();"))).scalar()
                print(f"Database name      : {db_name}")

            if settings.DATABASE_ALLOWED_OBJECTS:
                object_name = settings.DATABASE_ALLOWED_OBJECTS[0]
                try:
                    view_result = await conn.execute(
                        text(_view_test_sql(provider, object_name))
                    )
                    rows = view_result.mappings().all()
                    columns = list(rows[0].keys()) if rows else list(view_result.keys())
                    print(f"View accessibility : OK ({object_name})")
                    print(f"Columns            : {', '.join(columns)}")
                    print(f"Row count (max 5)  : {len(rows)}")
                except Exception as ve:
                    print(f"View accessibility : FAILED ({object_name})")
                    print(f"View test error    : {type(ve).__name__}: {ve}")
                    return 1
            else:
                print("View accessibility : skipped (DATABASE_ALLOWED_OBJECTS not configured)")
    except Exception as e:
        print("Connection test    : FAILED")
        print(f"Error              : {type(e).__name__}: {e}")
        return 1
    finally:
        await engine.dispose()

    print("Verification completed successfully. No row data was printed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
