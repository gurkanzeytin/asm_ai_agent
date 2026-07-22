"""Safe startup diagnostics logging (Part 7 of the NVIDIA/Nemotron integration).

Startup must safely log LLM_PROVIDER, OLLAMA_MODEL, NVIDIA_MODEL/base URL/"API
key configured: yes/no", and insight remote-routing settings — but never a
Gemini-specific line when Gemini isn't the active provider, and never a raw
secret value.
"""

import logging

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.main import app, lifespan


@pytest.mark.asyncio
async def test_startup_diagnostics_never_leak_nvidia_api_key(caplog, monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", SecretStr("nvapi-super-secret-value"))

    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            pass

    for record in caplog.records:
        assert "nvapi-super-secret-value" not in record.getMessage()


@pytest.mark.asyncio
async def test_startup_diagnostics_omit_gemini_lines_when_not_active(caplog, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")

    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            pass

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "GEMINI_MODEL" not in combined
    assert "GEMINI API KEY" not in combined


@pytest.mark.asyncio
async def test_startup_diagnostics_include_gemini_lines_when_active(caplog, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")

    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            pass

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "GEMINI_MODEL" in combined


@pytest.mark.asyncio
async def test_startup_diagnostics_report_nvidia_key_configured_yes_no(caplog, monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", SecretStr("nvapi-configured"))

    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            pass

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "NVIDIA API key configured : yes" in combined
    assert "nvapi-configured" not in combined


@pytest.mark.asyncio
async def test_startup_diagnostics_report_key_missing_as_no(caplog, monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", SecretStr(""))
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")

    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            pass

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "NVIDIA API key configured : no" in combined


@pytest.mark.asyncio
async def test_startup_diagnostics_include_insight_routing_settings(caplog, monkeypatch):
    monkeypatch.setattr(settings, "INSIGHT_ROUTING_ENABLED", True)
    monkeypatch.setattr(settings, "INSIGHT_REMOTE_COMPLEXITY_THRESHOLD", 3)

    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            pass

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "Insight remote routing enabled : True" in combined
    assert "Insight remote complexity threshold : 3" in combined
