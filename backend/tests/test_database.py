import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.database import SessionLocal, engine, get_db


def test_engine_initialization():
    """Verifies that the global async engine was initialized with standard configurations."""
    assert engine is not None
    assert isinstance(engine, AsyncEngine)


def test_session_factory_creation():
    """Verifies that the SessionLocal factory is created and returns active session instances."""
    assert SessionLocal is not None
    session = SessionLocal()
    assert isinstance(session, AsyncSession)
    # Tear down session
    assert session.is_active


@pytest.mark.asyncio
async def test_dependency_injection_lifecycle():
    """Verifies the async generator dependency yields and closes active session contexts."""
    session_generator = get_db()

    # Retrieve the yielded AsyncSession context
    session = await anext(session_generator)
    try:
        assert isinstance(session, AsyncSession)
        assert session.is_active
    finally:
        # Tear down generator to close the session context
        try:
            await anext(session_generator)
        except StopAsyncIteration:
            pass
