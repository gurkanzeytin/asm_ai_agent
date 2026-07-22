"""DELETE /api/v1/context/{session_id} — conversational memory reset endpoint."""

import pytest

from app.bootstrap import container


@pytest.mark.asyncio
async def test_reset_clears_only_the_target_session(client):
    manager = container.context_manager
    r1 = manager.resolve("Kardiyoloji doktorlarını göster", "reset-test-a")
    manager.update(r1, "reset-test-a")
    r2 = manager.resolve("Psikiyatri doktorlarını göster", "reset-test-b")
    manager.update(r2, "reset-test-b")

    response = await client.delete("/api/v1/context/reset-test-a")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "reset-test-a"
    assert body["memory_reset"] is True
    assert manager._store.get("reset-test-a").department is None
    assert manager._store.get("reset-test-b").department == "Psikiyatri"


@pytest.mark.asyncio
async def test_reset_missing_session_is_idempotent(client):
    response = await client.delete("/api/v1/context/never-existed-session")
    assert response.status_code == 200
    body = response.json()
    assert body["memory_reset"] is False

    response2 = await client.delete("/api/v1/context/never-existed-session")
    assert response2.status_code == 200
    assert response2.json()["memory_reset"] is False


@pytest.mark.asyncio
async def test_reset_response_never_leaks_other_sessions(client):
    manager = container.context_manager
    r = manager.resolve("Kardiyoloji doktorlarını göster", "reset-test-c")
    manager.update(r, "reset-test-c")

    response = await client.delete("/api/v1/context/reset-test-c")

    body = response.json()
    assert set(body.keys()) == {"session_id", "memory_reset"}
