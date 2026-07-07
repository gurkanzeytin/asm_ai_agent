import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Verifies the root endpoint returns the correct API metadata."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data == {"message": "ASM AI Agent API"}


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    """Verifies that the root health check endpoint returns the correct structure."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "ASM AI Agent"
    assert data["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_api_v1_health_endpoint(client: AsyncClient):
    """Verifies that the versioned v1 health route returns the correct structure."""
    response = await client.get("/api/v1/health/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "ASM AI Agent"
    assert data["version"] == "1.0.0"
