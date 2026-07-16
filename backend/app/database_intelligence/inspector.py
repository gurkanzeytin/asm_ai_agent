import logging
import time

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.database_intelligence.exceptions import DatabaseInspectionError
from app.database_intelligence.interfaces import IDatabaseInspector
from app.database_intelligence.models import (
    ColumnMetadata,
    DatabaseSchema,
    ForeignKeyMetadata,
    SchemaStatistics,
    TableMetadata,
    ViewMetadata,
    calculate_fingerprint,
)
from app.sql_validator.validator import normalize_object_name

logger = logging.getLogger(__name__)


class DatabaseInspector(IDatabaseInspector):
    """SQLAlchemy inspection API implementation of the IDatabaseInspector interface."""

    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    async def inspect_schema(self) -> DatabaseSchema:
        """Asynchronously inspects the database schema using run_sync and SQLAlchemy inspector APIs."""
        logger.info("Starting database schema metadata inspection.")
        start_time = time.perf_counter()

        try:
            async with self.engine.connect() as conn:
                schema = await conn.run_sync(self._inspect_sync)
            duration = (time.perf_counter() - start_time) * 1000

            logger.info(
                "Completed database schema inspection successfully.",
                extra={
                    "inspection_duration_ms": duration,
                    "tables_count": schema.statistics.table_count,
                    "columns_count": schema.statistics.column_count,
                    "foreign_keys_count": schema.statistics.foreign_key_count,
                    "views_count": schema.statistics.view_count,
                    "fingerprint": schema.fingerprint,
                },
            )
            return schema
        except DatabaseInspectionError:
            raise
        except Exception as e:
            logger.error(f"Critical error during database metadata inspection: {e}")
            raise DatabaseInspectionError(f"Database inspection failed: {e}") from e

    def _inspection_schema_name(self, connection) -> str | None:
        """Returns the explicit schema to inspect for schema-aware providers."""
        if connection.dialect.name == "mssql":
            return getattr(settings, "DATABASE_SCHEMA", "dbo") or "dbo"
        return None

    def _allowed_object_names(self, schema: str | None) -> set[str]:
        """Canonical allowed object set ('schema.name' lowercase). Empty means unrestricted."""
        default_schema = schema or getattr(settings, "DATABASE_SCHEMA", "dbo") or "dbo"
        return {
            normalize_object_name(item, default_schema)
            for item in getattr(settings, "DATABASE_ALLOWED_OBJECTS", [])
            if item
        }

    def _filter_allowed(
        self, names: list[str], schema: str | None, allowed: set[str]
    ) -> list[str]:
        """Filters object names to the allowed whitelist (no-op when unrestricted)."""
        if not allowed:
            return names
        effective_schema = schema or getattr(settings, "DATABASE_SCHEMA", "dbo") or "dbo"
        return [
            name
            for name in names
            if normalize_object_name(f"{effective_schema}.{name}", effective_schema) in allowed
        ]

    def _read_columns(
        self, inspector, object_name: str, schema: str | None
    ) -> list[ColumnMetadata]:
        """Reads column metadata for a table or view."""
        columns_data = inspector.get_columns(object_name, schema=schema)
        pks: list[str] = []
        try:
            pk_constraint = inspector.get_pk_constraint(object_name, schema=schema)
            pks = pk_constraint.get("constrained_columns", []) if pk_constraint else []
        except Exception:
            # Views and some dialects do not expose PK constraints.
            pass

        columns = []
        for col in columns_data:
            col_name = col["name"]
            columns.append(
                ColumnMetadata(
                    name=col_name,
                    type_name=str(col["type"]),
                    nullable=col["nullable"],
                    primary_key=(col_name in pks),
                    default=str(col["default"]) if col.get("default") is not None else None,
                    comment=col.get("comment"),
                )
            )
        return columns

    def _inspect_sync(self, connection) -> DatabaseSchema:
        """Synchronous inspection logic executed inside the run_sync thread context."""
        inspector = inspect(connection)
        schema_name = self._inspection_schema_name(connection)
        allowed = self._allowed_object_names(schema_name)

        # Retrieve structural lists (restricted to the configured schema when applicable)
        table_names = inspector.get_table_names(schema=schema_name)
        view_names = inspector.get_view_names(schema=schema_name)

        table_names = self._filter_allowed(table_names, schema_name, allowed)
        view_names = self._filter_allowed(view_names, schema_name, allowed)

        # Fail clearly when a configured allowed object cannot be found or accessed.
        if allowed:
            effective_schema = schema_name or getattr(settings, "DATABASE_SCHEMA", "dbo") or "dbo"
            discovered = {
                normalize_object_name(f"{effective_schema}.{name}", effective_schema)
                for name in [*table_names, *view_names]
            }
            missing = sorted(allowed - discovered)
            if missing:
                raise DatabaseInspectionError(
                    f"Configured allowed object(s) not found or not accessible: "
                    f"{', '.join(missing)}. Verify DATABASE_ALLOWED_OBJECTS and database "
                    f"permissions for the configured schema."
                )

        def qualified(name: str) -> str:
            return f"{schema_name}.{name}" if schema_name else name

        tables_metadata: dict[str, TableMetadata] = {}
        total_columns = 0
        total_fks = 0

        for table_name in table_names:
            columns = self._read_columns(inspector, table_name, schema_name)
            total_columns += len(columns)
            pks = [col.name for col in columns if col.primary_key]

            # Discover foreign keys
            fk_data = inspector.get_foreign_keys(table_name, schema=schema_name)
            foreign_keys = []
            for fk in fk_data:
                foreign_keys.append(
                    ForeignKeyMetadata(
                        constrained_columns=fk["constrained_columns"],
                        referred_schema=fk.get("referred_schema"),
                        referred_table=fk["referred_table"],
                        referred_columns=fk["referred_columns"],
                    )
                )
            total_fks += len(foreign_keys)

            # Discover table comment
            table_comment = None
            try:
                comment_dict = inspector.get_table_comment(table_name, schema=schema_name)
                table_comment = comment_dict.get("text") if comment_dict else None
            except Exception:
                # Dialect does not support get_table_comment
                pass

            display_name = qualified(table_name)
            tables_metadata[display_name] = TableMetadata(
                name=display_name,
                columns=columns,
                primary_keys=pks,
                foreign_keys=foreign_keys,
                comment=table_comment,
            )

        views_metadata: dict[str, ViewMetadata] = {}
        for view_name in view_names:
            view_comment = None
            try:
                comment_dict = inspector.get_view_comment(view_name, schema=schema_name)
                view_comment = comment_dict.get("text") if comment_dict else None
            except Exception:
                # Dialect does not support get_view_comment
                pass

            view_columns: list[ColumnMetadata] = []
            try:
                view_columns = self._read_columns(inspector, view_name, schema_name)
                total_columns += len(view_columns)
            except Exception:
                if allowed:
                    raise DatabaseInspectionError(
                        f"Could not read column metadata for allowed view "
                        f"'{qualified(view_name)}'. Verify view permissions."
                    ) from None
                # Best-effort for unrestricted (local development) inspection.

            display_name = qualified(view_name)
            views_metadata[display_name] = ViewMetadata(
                name=display_name,
                comment=view_comment,
                columns=view_columns,
            )

        # Build schema statistics
        statistics = SchemaStatistics(
            table_count=len(tables_metadata),
            column_count=total_columns,
            foreign_key_count=total_fks,
            view_count=len(views_metadata),
        )

        # Compute deterministic hash fingerprint
        fingerprint = calculate_fingerprint(tables_metadata, views_metadata)

        return DatabaseSchema(
            tables=tables_metadata,
            views=views_metadata,
            statistics=statistics,
            fingerprint=fingerprint,
        )
