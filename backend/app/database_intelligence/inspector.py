import logging
import time
from typing import Dict

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

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
        except Exception as e:
            logger.error(f"Critical error during database metadata inspection: {e}")
            raise DatabaseInspectionError(f"Database inspection failed: {e}") from e

    def _inspect_sync(self, connection) -> DatabaseSchema:
        """Synchronous inspection logic executed inside the run_sync thread context."""
        inspector = inspect(connection)

        # Retrieve structural lists
        table_names = inspector.get_table_names()
        view_names = inspector.get_view_names()

        tables_metadata: Dict[str, TableMetadata] = {}
        total_columns = 0
        total_fks = 0

        for table_name in table_names:
            # Discover columns
            columns_data = inspector.get_columns(table_name)
            pk_constraint = inspector.get_pk_constraint(table_name)
            pks = pk_constraint.get("constrained_columns", []) if pk_constraint else []

            columns = []
            for col in columns_data:
                col_name = col["name"]
                col_type = str(col["type"])
                col_nullable = col["nullable"]
                col_default = str(col["default"]) if col.get("default") is not None else None
                col_comment = col.get("comment")

                columns.append(
                    ColumnMetadata(
                        name=col_name,
                        type_name=col_type,
                        nullable=col_nullable,
                        primary_key=(col_name in pks),
                        default=col_default,
                        comment=col_comment,
                    )
                )
            total_columns += len(columns)

            # Discover foreign keys
            fk_data = inspector.get_foreign_keys(table_name)
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
                comment_dict = inspector.get_table_comment(table_name)
                table_comment = comment_dict.get("text") if comment_dict else None
            except Exception:
                # Dialect does not support get_table_comment
                pass

            tables_metadata[table_name] = TableMetadata(
                name=table_name,
                columns=columns,
                primary_keys=pks,
                foreign_keys=foreign_keys,
                comment=table_comment,
            )

        views_metadata: Dict[str, ViewMetadata] = {}
        for view_name in view_names:
            view_comment = None
            try:
                comment_dict = inspector.get_view_comment(view_name)
                view_comment = comment_dict.get("text") if comment_dict else None
            except Exception:
                # Dialect does not support get_view_comment
                pass

            views_metadata[view_name] = ViewMetadata(
                name=view_name,
                comment=view_comment,
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
