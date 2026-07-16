import hashlib
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ColumnMetadata(BaseModel):
    """Immutable representation of column metadata."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="The name of the database column.")
    type_name: str = Field(..., description="The database-specific type (e.g. VARCHAR(255), INT).")
    nullable: bool = Field(..., description="Indicates if the column supports null values.")
    primary_key: bool = Field(..., description="Indicates if the column is a primary key.")
    default: Optional[str] = Field(default=None, description="The default column value expression.")
    comment: Optional[str] = Field(default=None, description="Optional column description comment.")


class ForeignKeyMetadata(BaseModel):
    """Immutable representation of foreign key metadata."""

    model_config = ConfigDict(frozen=True)

    constrained_columns: List[str] = Field(..., description="Local columns matching foreign keys.")
    referred_schema: Optional[str] = Field(default=None, description="Target referred schema name.")
    referred_table: str = Field(..., description="Target referred table name.")
    referred_columns: List[str] = Field(..., description="Target referred primary key columns.")


class TableMetadata(BaseModel):
    """Immutable representation of table metadata."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="The table name.")
    columns: List[ColumnMetadata] = Field(..., description="List of columns in this table.")
    primary_keys: List[str] = Field(..., description="Table primary key column names.")
    foreign_keys: List[ForeignKeyMetadata] = Field(..., description="Table foreign key constraints.")
    comment: Optional[str] = Field(default=None, description="Optional table description comment.")


class ViewMetadata(BaseModel):
    """Immutable representation of lightweight view metadata."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="The view name.")
    comment: Optional[str] = Field(default=None, description="Optional view description comment.")
    columns: list[ColumnMetadata] = Field(
        default_factory=list, description="Optional list of columns exposed by the view."
    )


class SchemaStatistics(BaseModel):
    """Immutable representation of metadata diagnostics metrics."""

    model_config = ConfigDict(frozen=True)

    table_count: int = Field(..., description="Number of tables in the database.")
    column_count: int = Field(..., description="Total count of columns across all tables.")
    foreign_key_count: int = Field(..., description="Total count of foreign keys across all tables.")
    view_count: int = Field(..., description="Number of views in the database.")


class DatabaseSchema(BaseModel):
    """Immutable central representation of the entire discovered database schema."""

    model_config = ConfigDict(frozen=True)

    tables: Dict[str, TableMetadata] = Field(..., description="Discovered tables mapped by table name.")
    views: Dict[str, ViewMetadata] = Field(..., description="Discovered views mapped by view name.")
    statistics: SchemaStatistics = Field(..., description="Overall schema statistics metrics.")
    fingerprint: str = Field(..., description="Deterministic structural SHA-256 fingerprint hash.")


class DatabaseContext(BaseModel):
    """Immutable representation of the retrieved database metadata context."""

    model_config = ConfigDict(frozen=True)

    tables: List[TableMetadata] = Field(..., description="List of relevant table metadata.")
    views: List[ViewMetadata] = Field(..., description="List of relevant view metadata.")
    normalized_query: Optional[str] = Field(
        default=None,
        description="Query-analysis normalized question used for retrieval and SQL generation.",
    )


def calculate_fingerprint(tables: Dict[str, TableMetadata], views: Dict[str, ViewMetadata]) -> str:
    """Computes a deterministic structural fingerprint SHA-256 hash of the schema.

    The hash is stable across execution runs, changing only when structural components change.
    """
    elements = []

    # Sort table names for determinism
    for table_name in sorted(tables.keys()):
        table = tables[table_name]
        elements.append(f"table:{table.name}")
        
        # Sort columns by name for determinism
        sorted_cols = sorted(table.columns, key=lambda c: c.name)
        for col in sorted_cols:
            col_str = f"col:{col.name}:{col.type_name}:{col.nullable}:{col.primary_key}"
            elements.append(col_str)

        # Sort foreign keys for determinism
        sorted_fks = sorted(
            table.foreign_keys,
            key=lambda fk: (fk.referred_table, "".join(fk.constrained_columns))
        )
        for fk in sorted_fks:
            fk_str = f"fk:{''.join(fk.constrained_columns)}->{fk.referred_table}({''.join(fk.referred_columns)})"
            elements.append(fk_str)

    # Sort view names for determinism
    for view_name in sorted(views.keys()):
        elements.append(f"view:{view_name}")

    serialized = "|".join(elements)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
