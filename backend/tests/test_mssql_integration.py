"""Opt-in SQL Server integration tests against the live PusulaComed database.

These tests are SKIPPED by default and never run in CI. Enable explicitly with:

    RUN_MSSQL_INTEGRATION=1 pytest tests/test_mssql_integration.py

Requirements: network access to ASMPSHISBCK2, Microsoft ODBC Driver 18, and a
Windows account with read permission on dbo.vw_RandevuRaporu. Read-only: the
tests execute a bounded SELECT and never print row contents.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_MSSQL_INTEGRATION"),
    reason="Live SQL Server integration test; set RUN_MSSQL_INTEGRATION=1 to enable.",
)


@pytest.mark.asyncio
async def test_live_view_is_readable():
    from sqlalchemy import text

    from app.database.session import engine

    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT TOP (5) * FROM dbo.vw_RandevuRaporu;"))
        rows = result.mappings().all()

    assert rows, "dbo.vw_RandevuRaporu returned no rows"
    assert "Id" in rows[0]
    assert "BaslangicTarihi" in rows[0]
