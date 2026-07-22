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
    mock_session.stream = AsyncMock()

    repo = AnalyticalRepository(session=mock_session)

    # Configure mock execute result values
    execute_result = MagicMock()
    execute_result.returns_rows = True

    # Mappings returning row dictionaries
    row_mappings = [{"id": 1, "metric": "test_value"}]
    execute_result.mappings.return_value.fetchmany = AsyncMock(return_value=row_mappings)
    mock_session.stream.return_value = execute_result

    output = await repo.execute_query("SELECT 1;")
    assert output == row_mappings
    mock_session.stream.assert_called_once()
    execute_result.mappings.return_value.fetchmany.assert_called_once_with(1001)
    execute_result.mappings.return_value.all.assert_not_called()
    execute_result.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_repository_stream_result_does_not_require_sync_returns_rows_attribute():
    """Real SQLAlchemy AsyncResult exposes mappings(), but not returns_rows."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.stream = AsyncMock()
    execute_result = MagicMock(spec=["mappings", "close"])
    execute_result.mappings.return_value.fetchmany = AsyncMock(return_value=[{"value": 1}])
    mock_session.stream.return_value = execute_result

    output = await AnalyticalRepository(mock_session).execute_query("SELECT 1 AS value")

    assert output == [{"value": 1}]
    execute_result.mappings.return_value.fetchmany.assert_awaited_once_with(1001)
    execute_result.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_repository_mocked_140000_rows_uses_only_bounded_fetch():
    """A huge SELECT is sampled once and never materialized through all/fetchall."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.stream = AsyncMock()
    execute_result = MagicMock()
    execute_result.returns_rows = True
    bounded_rows = [{"value": index} for index in range(1001)]
    mappings = execute_result.mappings.return_value
    mappings.fetchmany = AsyncMock(return_value=bounded_rows)
    mock_session.stream.return_value = execute_result

    output = await AnalyticalRepository(mock_session).execute_query("SELECT value FROM huge_view")

    assert len(output) == 1001
    mappings.fetchmany.assert_called_once_with(1001)
    mappings.all.assert_not_called()
    assert not hasattr(mappings, "fetchall") or mappings.fetchall.call_count == 0
    execute_result.close.assert_called_once_with()


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
    execute_result.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_repository_fetch_paged_query():
    """Verifies paged fetches execute queries with correct limits and offsets."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.stream = AsyncMock()

    repo = AnalyticalRepository(session=mock_session)

    execute_result = MagicMock()
    execute_result.returns_rows = True
    execute_result.mappings.return_value.fetchmany = AsyncMock(return_value=[])
    mock_session.stream.return_value = execute_result

    await repo.fetch_paged_query("SELECT * FROM events", skip=10, limit=20)

    # Assert SQL Server OFFSET/FETCH pagination uses safely bound parameters
    called_arg = mock_session.stream.call_args[0][0]
    called_params = mock_session.stream.call_args[0][1]
    assert "OFFSET :skip ROWS FETCH NEXT :limit ROWS ONLY" in str(called_arg)
    assert "LIMIT" not in str(called_arg)
    assert called_params == {"skip": 10, "limit": 20}


@pytest.mark.asyncio
async def test_repository_exception_wrapping():
    """Verifies repository wraps execution failures into custom RepositoryError classes."""
    mock_session = MagicMock(spec=AsyncSession)
    mock_session.stream = AsyncMock()

    repo = AnalyticalRepository(session=mock_session)

    # Force query statement failure
    mock_session.stream.side_effect = Exception("Syntax error")
    with pytest.raises(RepositoryError) as exc_info:
        await repo.execute_query("INVALID SQL;")

    assert "Database query execution failed" in str(exc_info.value)
