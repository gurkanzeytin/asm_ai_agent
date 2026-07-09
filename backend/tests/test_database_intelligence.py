from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.database_intelligence import (
    DatabaseContext,
    DatabaseInspectionError,
    DatabaseInspector,
    DatabaseSchema,
    SchemaCache,
    SchemaCacheError,
    SchemaRetriever,
    calculate_fingerprint,
)
from app.database_intelligence.models import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaStatistics,
    TableMetadata,
    ViewMetadata,
)


@pytest.mark.asyncio
async def test_database_inspection_success():
    # Setup mock engine
    mock_engine = MagicMock(spec=AsyncEngine)
    mock_connection = MagicMock()
    mock_connection.run_sync = AsyncMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_connection

    # Mock SQLAlchemy inspector returned in run_sync helper
    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["appointments", "patients"]
    mock_inspector.get_view_names.return_value = ["appointment_summary"]
    mock_inspector.get_columns.side_effect = lambda table: [
        {"name": "id", "type": "INTEGER", "nullable": False, "default": "1", "comment": "ID Col"},
        {"name": "name", "type": "VARCHAR(255)", "nullable": True, "default": None, "comment": None},
    ]
    mock_inspector.get_pk_constraint.side_effect = lambda table: {"constrained_columns": ["id"]}
    mock_inspector.get_foreign_keys.side_effect = lambda table: (
        [
            {
                "constrained_columns": ["patient_id"],
                "referred_schema": None,
                "referred_table": "patients",
                "referred_columns": ["id"],
            }
        ]
        if table == "appointments"
        else []
    )

    mock_inspector.get_table_comment.side_effect = lambda table: {"text": f"{table} description"}
    mock_inspector.get_view_comment.side_effect = lambda view: {"text": f"{view} view comment"}

    # Helper context executor runner mock
    async def run_sync_mock(func, *args, **kwargs):
        mock_sync_conn = MagicMock()
        with patch("app.database_intelligence.inspector.inspect", return_value=mock_inspector):
            return func(mock_sync_conn, *args, **kwargs)

    mock_connection.run_sync.side_effect = run_sync_mock

    inspector = DatabaseInspector(mock_engine)
    schema = await inspector.inspect_schema()

    # Assertions
    assert isinstance(schema, DatabaseSchema)
    assert len(schema.tables) == 2
    assert "appointments" in schema.tables
    assert "patients" in schema.tables
    assert schema.statistics.table_count == 2
    assert schema.statistics.column_count == 4
    assert schema.statistics.view_count == 1
    assert schema.statistics.foreign_key_count == 1

    appointments = schema.tables["appointments"]
    assert appointments.comment == "appointments description"
    assert len(appointments.columns) == 2
    assert appointments.columns[0].name == "id"
    assert appointments.columns[0].primary_key is True
    assert appointments.columns[0].comment == "ID Col"
    assert appointments.columns[0].default == "1"
    assert appointments.columns[1].name == "name"
    assert appointments.columns[1].primary_key is False
    assert len(appointments.foreign_keys) == 1
    assert appointments.foreign_keys[0].referred_table == "patients"

    assert "appointment_summary" in schema.views
    assert schema.views["appointment_summary"].comment == "appointment_summary view comment"
    assert len(schema.fingerprint) == 64  # SHA-256 length


@pytest.mark.asyncio
async def test_fingerprint_consistency_and_change_detection():
    col1 = ColumnMetadata(name="id", type_name="INT", nullable=False, primary_key=True)
    col2 = ColumnMetadata(name="name", type_name="VARCHAR", nullable=True, primary_key=False)

    table1 = TableMetadata(name="users", columns=[col1, col2], primary_keys=["id"], foreign_keys=[])
    tables = {"users": table1}
    views = {"active_users": ViewMetadata(name="active_users")}

    fp1 = calculate_fingerprint(tables, views)
    fp2 = calculate_fingerprint(tables, views)
    assert fp1 == fp2

    # Modifying structural details should change the fingerprint
    col2_modified = ColumnMetadata(name="name", type_name="TEXT", nullable=True, primary_key=False)
    table1_modified = TableMetadata(
        name="users", columns=[col1, col2_modified], primary_keys=["id"], foreign_keys=[]
    )
    tables_modified = {"users": table1_modified}
    fp3 = calculate_fingerprint(tables_modified, views)
    assert fp1 != fp3


@pytest.mark.asyncio
async def test_database_inspection_failure():
    mock_engine = MagicMock(spec=AsyncEngine)
    mock_engine.connect.side_effect = Exception("DB Connection Down")

    inspector = DatabaseInspector(mock_engine)
    with pytest.raises(DatabaseInspectionError):
        await inspector.inspect_schema()


@pytest.mark.asyncio
async def test_schema_cache_behavior():
    mock_inspector = MagicMock(spec=DatabaseInspector)

    dummy_schema1 = DatabaseSchema(
        tables={},
        views={},
        statistics=SchemaStatistics(table_count=0, column_count=0, foreign_key_count=0, view_count=0),
        fingerprint="fp1",
    )
    dummy_schema2 = DatabaseSchema(
        tables={},
        views={},
        statistics=SchemaStatistics(table_count=0, column_count=0, foreign_key_count=0, view_count=0),
        fingerprint="fp2",
    )

    mock_inspector.inspect_schema.side_effect = [dummy_schema1, dummy_schema2]

    cache = SchemaCache(mock_inspector)
    # Enable cache explicitly
    cache.cache_enabled = True
    cache.cache_ttl = 100.0

    # 1. Miss - fetches from inspector
    schema1 = await cache.get_schema()
    assert schema1.fingerprint == "fp1"
    assert cache.current_version == "fp1"
    assert mock_inspector.inspect_schema.call_count == 1

    # 2. Hit - retrieves from cache
    schema2 = await cache.get_schema()
    assert schema2.fingerprint == "fp1"
    assert mock_inspector.inspect_schema.call_count == 1

    # 3. Invalidate
    cache.invalidate()
    assert cache.current_version is None

    # 4. Fetch after invalidate - miss
    schema3 = await cache.get_schema()
    assert schema3.fingerprint == "fp2"
    assert mock_inspector.inspect_schema.call_count == 2

    # 5. Force refresh
    mock_inspector.inspect_schema.side_effect = [dummy_schema1]
    await cache.refresh()
    assert cache.current_version == "fp1"
    assert mock_inspector.inspect_schema.call_count == 3


@pytest.mark.asyncio
async def test_schema_cache_ttl_and_refresh_behavior():
    mock_inspector = MagicMock(spec=DatabaseInspector)
    dummy_schema = DatabaseSchema(
        tables={},
        views={},
        statistics=SchemaStatistics(table_count=0, column_count=0, foreign_key_count=0, view_count=0),
        fingerprint="fp1",
    )
    mock_inspector.inspect_schema.return_value = dummy_schema

    cache = SchemaCache(mock_inspector)
    cache.cache_enabled = True
    cache.cache_ttl = -1.0  # Expired immediately
    cache.auto_refresh = True

    await cache.get_schema()
    assert mock_inspector.inspect_schema.call_count == 1

    # Expired, triggers auto refresh
    await cache.get_schema()
    assert mock_inspector.inspect_schema.call_count == 2


@pytest.mark.asyncio
async def test_schema_retriever_keyword():
    # Set up tables
    col_app_id = ColumnMetadata(
        name="id", type_name="INTEGER", nullable=False, primary_key=True, comment="Appointment identifier"
    )
    col_app_patient = ColumnMetadata(name="patient_id", type_name="INTEGER", nullable=False, primary_key=False)
    table_appointments = TableMetadata(
        name="appointments",
        columns=[col_app_id, col_app_patient],
        primary_keys=["id"],
        foreign_keys=[],
        comment="Stores patient scheduled appointments data",
    )

    col_pat_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
    col_pat_name = ColumnMetadata(name="full_name", type_name="VARCHAR", nullable=True, primary_key=False)
    table_patients = TableMetadata(
        name="patients",
        columns=[col_pat_id, col_pat_name],
        primary_keys=["id"],
        foreign_keys=[],
        comment="Registry of patients",
    )

    table_audit = TableMetadata(
        name="system_audit_logs",
        columns=[ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)],
        primary_keys=["id"],
        foreign_keys=[],
        comment="System debug log entries",
    )

    view_active = ViewMetadata(name="active_appointments_view", comment="Active scheduled appointments")

    schema = DatabaseSchema(
        tables={
            "appointments": table_appointments,
            "patients": table_patients,
            "system_audit_logs": table_audit,
        },
        views={"active_appointments_view": view_active},
        statistics=SchemaStatistics(table_count=3, column_count=5, foreign_key_count=0, view_count=1),
        fingerprint="fingerprint",
    )

    retriever = SchemaRetriever(match_threshold=1)

    # Search for "Appointments yesterday"
    context = retriever.retrieve_context("Appointments yesterday", schema)

    assert isinstance(context, DatabaseContext)
    # appointments table and active_appointments_view should be in context
    assert len(context.tables) >= 1
    assert any(t.name == "appointments" for t in context.tables)
    assert any(v.name == "active_appointments_view" for v in context.views)
    assert not any(t.name == "system_audit_logs" for t in context.tables)

    # Search for audit
    context2 = retriever.retrieve_context("system audit log queries", schema)
    assert any(t.name == "system_audit_logs" for t in context2.tables)
    assert not any(t.name == "patients" for t in context2.tables)


def test_schema_retriever_fallback_caps():
    # Setup 8 dummy tables (more than fallback cap 5)
    tables = {}
    for i in range(1, 9):
        col_id = ColumnMetadata(name="id", type_name="INTEGER", nullable=False, primary_key=True)
        table = TableMetadata(
            name=f"table_{i}",
            columns=[col_id],
            primary_keys=["id"],
            foreign_keys=[],
        )
        tables[f"table_{i}"] = table

    schema = DatabaseSchema(
        tables=tables,
        views={},
        statistics=SchemaStatistics(table_count=8, column_count=8, foreign_key_count=0, view_count=0),
        fingerprint="fp-fallback-test",
    )

    # Use explicit constructor values to override settings if necessary
    retriever = SchemaRetriever(match_threshold=1, max_tables=5, max_columns_per_table=15)
    
    # Query matching nothing to trigger fallback branch
    context = retriever.retrieve_context("match nothing query", schema)

    assert len(context.tables) == 5
    assert [t.name for t in context.tables] == ["table_1", "table_2", "table_3", "table_4", "table_5"]


def test_schema_retriever_column_caps_preserves_pks_and_fks():
    # Table with 20 columns: pk_col, fk_col, plus 18 other cols.
    # We want to cap at 3 columns.
    columns = [
        ColumnMetadata(name="pk_col", type_name="INTEGER", nullable=False, primary_key=True),
        ColumnMetadata(name="fk_col", type_name="INTEGER", nullable=False, primary_key=False),
    ]
    for i in range(1, 19):
        columns.append(ColumnMetadata(name=f"col_{i}", type_name="VARCHAR", nullable=True, primary_key=False))

    fk = ForeignKeyMetadata(
        constrained_columns=["fk_col"],
        referred_table="other_table",
        referred_columns=["id"],
    )

    table = TableMetadata(
        name="test_table",
        columns=columns,
        primary_keys=["pk_col"],
        foreign_keys=[fk],
    )

    schema = DatabaseSchema(
        tables={"test_table": table},
        views={},
        statistics=SchemaStatistics(table_count=1, column_count=20, foreign_key_count=1, view_count=0),
        fingerprint="fp-col-cap-test",
    )

    # Cap to max 3 columns per table
    retriever = SchemaRetriever(match_threshold=1, max_tables=5, max_columns_per_table=3)

    # Query matching nothing to trigger fallback branch
    context = retriever.retrieve_context("match nothing query", schema)
    
    assert len(context.tables) == 1
    capped_table = context.tables[0]
    assert len(capped_table.columns) == 3

    # Primary key (pk_col) and Foreign key (fk_col) MUST be preserved in the capped column list
    col_names = [c.name for c in capped_table.columns]
    assert "pk_col" in col_names
    assert "fk_col" in col_names
    assert "col_1" in col_names


def test_schema_retriever_synonym_expansion_and_diacritic_normalization():
    # Schema matches Turkish doctor/appointment words (doktor, randevu)
    col_id = ColumnMetadata(name="sehir_id", type_name="INTEGER", nullable=False, primary_key=True)
    table_doktor = TableMetadata(
        name="doktorlar",
        columns=[col_id],
        primary_keys=["sehir_id"],
        foreign_keys=[],
        comment="Doktor bilgileri",
    )

    schema = DatabaseSchema(
        tables={"doktorlar": table_doktor},
        views={},
        statistics=SchemaStatistics(table_count=1, column_count=1, foreign_key_count=0, view_count=0),
        fingerprint="fp-synonym-test",
    )

    retriever = SchemaRetriever(match_threshold=1)

    # Query with English terms: "Which doctor has highest name?"
    # "doctor" should map to "doktor", matching "doktorlar" table.
    context = retriever.retrieve_context("Which doctor has highest name?", schema)

    assert len(context.tables) == 1
    assert context.tables[0].name == "doktorlar"

    # Test diacritic normalization explicitly:
    # Querying "şehir" or "ŞEHİR" should normalize and match "sehir_id" column,
    # raising the score above threshold.
    context_diacritic = retriever.retrieve_context("Which şehir doctor?", schema)
    assert len(context_diacritic.tables) == 1
    assert context_diacritic.tables[0].name == "doktorlar"

