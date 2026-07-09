import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai import types

from app.llm.gemini import GeminiProvider
from app.llm.schemas import LLMResponse


@pytest.fixture
def mock_genai_client():
    with patch("app.llm.gemini.genai.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = AsyncMock()
        mock_client_class.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
async def test_gemini_generate_fallback_extraction_parts(mock_genai_client):
    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")

    # Setup response where .text property raises an exception, but content parts exist
    mock_response = MagicMock()
    type(mock_response).text = property(lambda self: (_ for _ in ()).throw(ValueError("Text unavailable")))
    
    mock_response.usage_metadata = None

    # Setup parts on candidates
    mock_part1 = MagicMock()
    mock_part1.text = "SELECT * "
    mock_part2 = MagicMock()
    mock_part2.text = "FROM doctors;"
    
    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "STOP"
    mock_candidate.content.parts = [mock_part1, mock_part2]
    mock_response.candidates = [mock_candidate]

    mock_genai_client.aio.models.generate_content.return_value = mock_response

    # Execute
    res = await provider.generate(prompt="get doctors", think=False)

    assert isinstance(res, LLMResponse)
    assert res.content == "SELECT * FROM doctors;"
    assert res.finish_reason == "stop"


@pytest.mark.asyncio
async def test_gemini_generate_non_stop_warning(mock_genai_client, caplog):
    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")

    mock_response = MagicMock()
    mock_response.text = "SELECT name FR"
    mock_response.usage_metadata = None

    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "MAX_TOKENS"
    mock_response.candidates = [mock_candidate]
    mock_genai_client.aio.models.generate_content.return_value = mock_response

    with caplog.at_level(logging.WARNING):
        res = await provider.generate(prompt="get patients", think=False)
        assert res.finish_reason == "max_tokens"
        
        # Verify warning log was emitted
        warnings = [rec.message for rec in caplog.records if rec.levelno == logging.WARNING]
        assert any("Generation terminated with non-stop reason: max_tokens" in w for w in warnings)


@pytest.mark.asyncio
async def test_gemini_generate_effective_config_debug_log(mock_genai_client, caplog):
    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")

    mock_response = MagicMock()
    mock_response.text = "Result"
    mock_response.usage_metadata = None
    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "STOP"
    mock_response.candidates = [mock_candidate]
    mock_genai_client.aio.models.generate_content.return_value = mock_response

    with caplog.at_level(logging.DEBUG):
        await provider.generate(prompt="get list", think=True, options={"temperature": 0.3})
        
        # Verify the effective config debug message was logged
        debugs = [rec.message for rec in caplog.records if rec.levelno == logging.DEBUG]
        assert any("Gemini Client sending request with GenerateContentConfig:" in d for d in debugs)
        assert any("temperature: 0.3" in d for d in debugs)
