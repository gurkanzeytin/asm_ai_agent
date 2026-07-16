"""Tests for SQL Server (mssql+aioodbc) support: settings, engine options,
read-only object whitelisting, T-SQL pagination, and retryable error handling.

No test in this module opens a real database connection.
"""

import pytest

from app.agent.nodes.execute_sql import _retryable_error
from app.core.settings import Settings
from app.database.session import DatabaseInitializationError, build_engine_options
from app.repositories.base import build_paged_query
from app.sql_validator.validator import SQLValidator, normalize_object_name

MSSQL_URL = (
    "mssql+aioodbc://@ASMPSHISBCK2/PusulaComed"
    "?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes"
)


# ---------------------------------------------------------------------------
# Settings parsing
# ---------------------------------------------------------------------------


def test_allowed_objects_parses_comma_separated_string():
    settings = Settings(DATABASE_ALLOWED_OBJECTS="dbo.vw_RandevuRaporu, dbo.vw_Other")
    assert settings.DATABASE_ALLOWED_OBJECTS == ["dbo.vw_RandevuRaporu", "dbo.vw_Other"]


def test_allowed_objects_parses_from_environment_variable(monkeypatch):
    monkeypatch.setenv("DATABASE_ALLOWED_OBJECTS", "dbo.vw_RandevuRaporu,dbo.vw_Other")
    settings = Settings(_env_file=None)
    assert settings.DATABASE_ALLOWED_OBJECTS == ["dbo.vw_RandevuRaporu", "dbo.vw_Other"]


def test_allowed_objects_defaults_to_empty_list():
    settings = Settings(_env_file=None)
    assert settings.DATABASE_ALLOWED_OBJECTS == []


def test_database_schema_and_timeout_defaults():
    settings = Settings(_env_file=None)
    assert settings.DATABASE_SCHEMA == "dbo"
    assert settings.DATABASE_CONNECT_TIMEOUT == 15
    assert settings.DATABASE_QUERY_TIMEOUT == 30


# ---------------------------------------------------------------------------
# Engine option selection (no real connection)
# ---------------------------------------------------------------------------


def test_sqlite_engine_options_preserved():
    options = build_engine_options("sqlite+aiosqlite:///./data/hospital_demo.db")
    assert options["connect_args"] == {"check_same_thread": False}
    assert "pool_size" not in options


def test_postgresql_engine_options_preserved():
    options = build_engine_options("postgresql+asyncpg://u:p@localhost:5432/db")
    assert options["pool_size"] > 0
    assert options["max_overflow"] == 10


def test_mssql_engine_options():
    options = build_engine_options(MSSQL_URL)
    assert options["pool_pre_ping"] is True
    assert options["pool_recycle"] == 1800
    assert options["pool_size"] > 0
    assert options["max_overflow"] == 5
    assert "timeout" in options["connect_args"]
    assert "check_same_thread" not in options.get("connect_args", {})


def test_mssql_requires_aioodbc_driver_scheme():
    with pytest.raises(DatabaseInitializationError):
        build_engine_options("mssql+pyodbc://@SERVER/Db?driver=ODBC+Driver+18+for+SQL+Server")


# ---------------------------------------------------------------------------
# Read-only object whitelist validation (T-SQL dialect)
# ---------------------------------------------------------------------------


def _tsql_validator() -> SQLValidator:
    return SQLValidator(
        dialect="tsql",
        allowed_objects=["dbo.vw_RandevuRaporu"],
        default_schema="dbo",
    )


def test_normalize_object_name_variants():
    assert normalize_object_name("dbo.vw_RandevuRaporu", "dbo") == "dbo.vw_randevuraporu"
    assert normalize_object_name("[dbo].[vw_RandevuRaporu]", "dbo") == "dbo.vw_randevuraporu"
    assert normalize_object_name("vw_RandevuRaporu", "dbo") == "dbo.vw_randevuraporu"


def test_allowed_view_select_passes():
    result = _tsql_validator().validate("SELECT TOP (100) * FROM dbo.vw_RandevuRaporu;")
    assert result.valid is True


def test_bracketed_identifier_passes():
    result = _tsql_validator().validate("SELECT TOP (10) * FROM [dbo].[vw_RandevuRaporu];")
    assert result.valid is True


def test_unqualified_allowed_view_resolves_with_default_schema():
    result = _tsql_validator().validate("SELECT COUNT(*) FROM vw_RandevuRaporu;")
    assert result.valid is True


def test_unqualified_view_rejected_with_other_default_schema():
    validator = SQLValidator(
        dialect="tsql", allowed_objects=["dbo.vw_RandevuRaporu"], default_schema="sales"
    )
    result = validator.validate("SELECT COUNT(*) FROM vw_RandevuRaporu;")
    assert result.valid is False


def test_forbidden_table_rejected():
    result = _tsql_validator().validate("SELECT * FROM dbo.Patients;")
    assert result.valid is False
    assert "allowed object" in (result.reason or "")


def test_forbidden_join_rejected():
    result = _tsql_validator().validate(
        "SELECT r.* FROM dbo.vw_RandevuRaporu r JOIN dbo.Secret s ON r.id = s.id;"
    )
    assert result.valid is False


def test_cte_over_allowed_view_passes():
    sql = (
        "WITH aylik AS (SELECT COUNT(*) AS adet FROM dbo.vw_RandevuRaporu) "
        "SELECT adet FROM aylik;"
    )
    result = _tsql_validator().validate(sql)
    assert result.valid is True


def test_linked_server_reference_rejected():
    result = _tsql_validator().validate("SELECT * FROM srv.OtherDb.dbo.vw_RandevuRaporu;")
    assert result.valid is False


def test_multiple_statements_rejected():
    result = _tsql_validator().validate(
        "SELECT * FROM dbo.vw_RandevuRaporu; SELECT * FROM dbo.vw_RandevuRaporu;"
    )
    assert result.valid is False


def test_dml_rejected():
    for sql in (
        "INSERT INTO dbo.vw_RandevuRaporu (a) VALUES (1);",
        "UPDATE dbo.vw_RandevuRaporu SET a = 1;",
        "DELETE FROM dbo.vw_RandevuRaporu;",
        "TRUNCATE TABLE dbo.vw_RandevuRaporu;",
        "DROP VIEW dbo.vw_RandevuRaporu;",
    ):
        result = _tsql_validator().validate(sql)
        assert result.valid is False, sql


def test_select_into_rejected():
    result = _tsql_validator().validate(
        "SELECT * INTO dbo.copy_table FROM dbo.vw_RandevuRaporu;"
    )
    assert result.valid is False


def test_exec_rejected():
    for sql in ("EXEC sp_who;", "EXECUTE sp_executesql N'SELECT 1';"):
        result = _tsql_validator().validate(sql)
        assert result.valid is False, sql


def test_openrowset_rejected():
    result = _tsql_validator().validate(
        "SELECT * FROM OPENROWSET('SQLNCLI', 'Server=x', 'SELECT 1');"
    )
    assert result.valid is False


def test_use_statement_rejected():
    result = _tsql_validator().validate("USE master;")
    assert result.valid is False


def test_empty_whitelist_disables_object_restriction():
    validator = SQLValidator(dialect="sqlite", allowed_objects=[], default_schema="dbo")
    result = validator.validate("SELECT * FROM patients;")
    assert result.valid is True


# ---------------------------------------------------------------------------
# SQL Server pagination
# ---------------------------------------------------------------------------


def test_paged_query_sqlite_uses_limit_offset():
    paged = build_paged_query("SELECT * FROM patients", "sqlite")
    assert "LIMIT :limit OFFSET :skip" in paged


def test_paged_query_mssql_with_order_by_uses_offset_fetch():
    paged = build_paged_query("SELECT ad FROM dbo.vw_RandevuRaporu ORDER BY ad", "mssql")
    assert paged.endswith("OFFSET :skip ROWS FETCH NEXT :limit ROWS ONLY;")
    assert "LIMIT" not in paged
    assert "(SELECT NULL)" not in paged


def test_paged_query_mssql_without_order_by_adds_neutral_order():
    paged = build_paged_query("SELECT ad FROM dbo.vw_RandevuRaporu", "mssql")
    assert "ORDER BY (SELECT NULL) OFFSET :skip ROWS FETCH NEXT :limit ROWS ONLY" in paged
    assert "LIMIT" not in paged


def test_paged_query_mssql_with_top_is_wrapped():
    paged = build_paged_query("SELECT TOP (100) ad FROM dbo.vw_RandevuRaporu", "mssql")
    assert paged.startswith("SELECT * FROM (")
    assert "FETCH NEXT :limit ROWS ONLY" in paged


@pytest.mark.asyncio
async def test_paged_query_rejects_invalid_bounds():
    from unittest.mock import AsyncMock

    from app.repositories.base import AnalyticalRepository
    from app.repositories.exceptions import RepositoryError

    repo = AnalyticalRepository(session=AsyncMock())
    with pytest.raises(RepositoryError):
        await repo.fetch_paged_query("SELECT 1", skip=-1, limit=10)
    with pytest.raises(RepositoryError):
        await repo.fetch_paged_query("SELECT 1", skip=0, limit=0)
    with pytest.raises(RepositoryError):
        await repo.fetch_paged_query("SELECT 1", skip=0, limit=10_000_000)


# ---------------------------------------------------------------------------
# Retryable SQL Server errors
# ---------------------------------------------------------------------------


def test_mssql_sql_shaped_errors_are_retryable():
    for message in (
        "Invalid column name 'hasta_adi'.",
        "Invalid object name 'dbo.vw_Randevu'.",
        "Ambiguous column name 'id'.",
        "Incorrect syntax near 'FORM'.",
        "Column 'x' is invalid in the select list because it is not contained in "
        "either an aggregate function or the GROUP BY clause.",
        "ORDER BY items must appear in the select list if SELECT DISTINCT is specified.",
        "The multi-part identifier \"r.ad\" could not be bound.",
    ):
        assert _retryable_error(message) is True, message


def test_auth_network_timeout_errors_are_not_retryable():
    for message in (
        "Login failed for user 'ASM1\\gurkan.zeytin'.",
        "The SELECT permission was denied on the object 'vw_RandevuRaporu'.",
        "A network-related or instance-specific error occurred while establishing "
        "a connection to SQL Server. The server was not found or was not accessible.",
        "Query timeout expired.",
        "Communication link failure",
        "SSL Provider: The certificate chain was issued by an authority that is not trusted.",
    ):
        assert _retryable_error(message) is False, message


# ---------------------------------------------------------------------------
# Schema filtering (inspector helpers, no connection)
# ---------------------------------------------------------------------------


def test_inspector_filters_objects_to_whitelist(monkeypatch):
    from app.core.config import settings as app_settings
    from app.database.session import engine
    from app.database_intelligence.inspector import DatabaseInspector

    monkeypatch.setattr(app_settings, "DATABASE_ALLOWED_OBJECTS", ["dbo.vw_RandevuRaporu"])
    monkeypatch.setattr(app_settings, "DATABASE_SCHEMA", "dbo")

    inspector = DatabaseInspector(engine)
    allowed = inspector._allowed_object_names("dbo")
    filtered = inspector._filter_allowed(
        ["vw_RandevuRaporu", "Patients", "SecretTable"], "dbo", allowed
    )
    assert filtered == ["vw_RandevuRaporu"]


def test_inspector_unrestricted_when_whitelist_empty(monkeypatch):
    from app.core.config import settings as app_settings
    from app.database.session import engine
    from app.database_intelligence.inspector import DatabaseInspector

    monkeypatch.setattr(app_settings, "DATABASE_ALLOWED_OBJECTS", [])

    inspector = DatabaseInspector(engine)
    allowed = inspector._allowed_object_names(None)
    names = ["patients", "appointments"]
    assert inspector._filter_allowed(names, None, allowed) == names
