import asyncio
import logging
import sys
from pathlib import Path

# Add backend directory to sys.path to resolve 'app' correctly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.bootstrap import container


async def main():
    # Fetch SchemaCache directly from the centralized dependency container
    cache = container.schema_cache

    print("Fetching schema metadata...")
    schema = await cache.get_schema()

    print("\n===== DATABASE METADATA DIAGNOSTICS =====")
    print(f"Schema Fingerprint : {schema.fingerprint}")

    stats = schema.statistics
    print(f"Total Tables       : {stats.table_count}")
    print(f"Total Columns      : {stats.column_count}")
    print(f"Total Foreign Keys : {stats.foreign_key_count}")
    print(f"Total Views        : {stats.view_count}")

    print("\n===== DETECTED TABLES =====")
    for table in schema.tables.values():
        print(f"\n- Table: {table.name}")
        if table.comment:
            print(f"  Description: {table.comment}")
        print("  Columns:")
        for col in table.columns:
            pk = " [PK]" if col.primary_key else ""
            null_label = "NULL" if col.nullable else "NOT NULL"
            default_expr = f" DEFAULT {col.default}" if col.default else ""
            col_comment = f" - Comment: {col.comment}" if col.comment else ""
            print(f"    * {col.name} ({col.type_name}){pk} [{null_label}]{default_expr}{col_comment}")

        if table.foreign_keys:
            print("  Foreign Keys:")
            for fk in table.foreign_keys:
                print(
                    f"    * ({', '.join(fk.constrained_columns)}) -> {fk.referred_table}({', '.join(fk.referred_columns)})"
                )

    if schema.views:
        print("\n===== DETECTED VIEWS =====")
        for view in schema.views.values():
            print(f"- View: {view.name}")
            if view.comment:
                print(f"  Description: {view.comment}")
    else:
        print("\nNo views detected in schema index.")


if __name__ == "__main__":
    # Configure logs to suppress verbose setup logs for clean validation print output
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app.bootstrap").setLevel(logging.WARNING)
    logging.getLogger("app.database_intelligence").setLevel(logging.WARNING)
    asyncio.run(main())