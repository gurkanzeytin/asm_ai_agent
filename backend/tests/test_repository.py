from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import AnalyticalRepository
from app.repositories.exceptions import RepositoryError


def test_repository_initialization():
    """Verifies repository initialization using constructor session injections."""
    mock_session = MagicMock(spec=AsyncSession)
    repo = AnalyticalRepository(session=mock_session)
    assert repo.session == mock_session


@pytest.mark.asyncio
async def test_repository_execute_query():
    """Verifies execute_query invokes SQL executes and returns mapped results."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()

    repo = AnalyticalRepository(session=mock_session)

    # Configure mock execute result values
    execute_result = MagicMock()
    execute_result.returns_rows = True

    # Mappings returning row dictionaries
    row_mappings = [{"id": 1, "metric": "test_value"}]
    execute_result.mappings.return_value.all.return_value = row_mappings
    mock_session.execute.return_value = execute_result

    output = await repo.execute_query("SELECT 1;")
    assert output == row_mappings
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_repository_execute_scalar():
    """Verifies execute_scalar fetches singular values successfully."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()

    repo = AnalyticalRepository(session=mock_session)

    execute_result = MagicMock()
    execute_result.scalar.return_value = 100
    mock_session.execute.return_value = execute_result

    val = await repo.execute_scalar("SELECT COUNT(*) FROM reports;")
    assert val == 100
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_repository_fetch_paged_query():
    """Verifies paged fetches execute queries with correct limits and offsets."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()

    repo = AnalyticalRepository(session=mock_session)

    execute_result = MagicMock()
    execute_result.returns_rows = True
    execute_result.mappings.return_value.all.return_value = []
    mock_session.execute.return_value = execute_result

    await repo.fetch_paged_query("SELECT * FROM events", skip=10, limit=20)

    # Assert SQL Server OFFSET/FETCH pagination uses safely bound parameters
    called_arg = mock_session.execute.call_args[0][0]
    called_params = mock_session.execute.call_args[0][1]
    assert "OFFSET :skip ROWS FETCH NEXT :limit ROWS ONLY" in str(called_arg)
    assert "LIMIT" not in str(called_arg)
    assert called_params == {"skip": 10, "limit": 20}


@pytest.mark.asyncio
async def test_repository_exception_wrapping():
    """Verifies repository wraps execution failures into custom RepositoryError classes."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.execute = AsyncMock()

    repo = AnalyticalRepository(session=mock_session)

    # Force query statement failure
    mock_session.execute.side_effect = Exception("Syntax error")
    with pytest.raises(RepositoryError) as exc_info:
        await repo.execute_query("INVALID SQL;")

    assert "Database query execution failed" in str(exc_info.value)
