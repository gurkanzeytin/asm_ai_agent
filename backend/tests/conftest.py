from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.database import get_db
from app.main import app
from app.models.base import Base

# In-memory test double for the get_db dependency override. The runtime database is
# Microsoft SQL Server only; unit tests never connect to it. This empty in-memory
# engine merely satisfies session wiring for API tests whose services are mocked.
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _unrestricted_object_whitelist(monkeypatch):
    """Disables the runtime object whitelist for generic unit tests.

    Production restricts queries to DATABASE_ALLOWED_OBJECTS (dbo.vw_RandevuRaporu).
    Whitelist enforcement has its own dedicated tests (test_mssql_support.py) that
    pass allowed_objects explicitly; legacy unit tests validate statement-level
    safety against generic fixtures and run unrestricted.
    """
    monkeypatch.setattr(settings, "DATABASE_ALLOWED_OBJECTS", [])


@pytest_asyncio.fixture
async def test_engine():
    """Constructs the isolated in-memory test-double engine (no dummy data, no tables)."""
    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Generates transactional sessions for each isolated test case."""
    session_factory = async_sessionmaker(bind=test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client targeting FastAPI app with overridden DB connection hooks."""

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
