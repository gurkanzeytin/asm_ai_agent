import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai.errors import APIError

from app.core.config import settings
from app.llm.exceptions import (
    LLMConnectionError,
    LLMException,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.gemini import GeminiProvider
from app.llm.provider import LLMFactory
from app.llm.schemas import LLMResponse


@pytest.fixture
def mock_genai_client():
    with patch("app.llm.gemini.genai.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = AsyncMock()
        mock_client_class.return_value = mock_client
        yield mock_client


def test_gemini_provider_initialization(mock_genai_client):
    with patch.object(settings, "GEMINI_API_KEY", "test-key-123"), patch.object(settings, "GEMINI_MODEL", "test-model"):
        provider = GeminiProvider()
        assert provider.api_key == "test-key-123"
        assert provider.model == "test-model"
        # Check client init args
        from google import genai
        genai.Client.assert_called_once_with(api_key="test-key-123")


@pytest.mark.asyncio
async def test_gemini_generate_success(mock_genai_client):
    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")

    # Mock API Response structure
    mock_response = MagicMock()
    mock_response.text = "Hello patient."
    mock_response.usage_metadata = MagicMock()
    mock_response.usage_metadata.prompt_token_count = 15
    mock_response.usage_metadata.candidates_token_count = 20

    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "STOP"
    mock_response.candidates = [mock_candidate]

    # Setup async model generate_content mock
    mock_genai_client.aio.models.generate_content.return_value = mock_response

    response = await provider.generate(prompt="Hello", think=True, options={"temperature": 0.5, "num_predict": 100})

    assert isinstance(response, LLMResponse)
    assert response.content == "Hello patient."
    assert response.model == "gemini-2.5-flash"
    assert response.prompt_tokens == 15
    assert response.completion_tokens == 20
    assert response.finish_reason == "stop"

    # Check GenerateContentConfig generation
    mock_genai_client.aio.models.generate_content.assert_called_once()
    call_args = mock_genai_client.aio.models.generate_content.call_args[1]
    assert call_args["model"] == "gemini-2.5-flash"
    assert call_args["contents"] == "Hello"
    assert call_args["config"].temperature == 0.5
    assert call_args["config"].max_output_tokens == 100


@pytest.mark.asyncio
async def test_gemini_generate_finish_reasons_normalization(mock_genai_client):
    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")

    mock_response = MagicMock()
    mock_response.text = "Response text"
    mock_response.usage_metadata = None

    mock_candidate = MagicMock()
    mock_candidate.finish_reason = "MAX_TOKENS"
    mock_response.candidates = [mock_candidate]
    mock_genai_client.aio.models.generate_content.return_value = mock_response

    res = await provider.generate("hello")
    assert res.finish_reason == "max_tokens"

    # Test safety reason
    mock_candidate.finish_reason = "SAFETY"
    res_safety = await provider.generate("hello")
    assert res_safety.finish_reason == "safety"

    # Test other/custom reason
    mock_candidate.finish_reason = "OTHER_REASON"
    res_other = await provider.generate("hello")
    assert res_other.finish_reason == "other_reason"


@pytest.mark.asyncio
async def test_gemini_api_error_mapping(mock_genai_client):
    provider = GeminiProvider(api_key="test-key")

    # 1. Test Timeout mapping (status 504 / timeout text)
    err_timeout = APIError(code=504, response_json={"error": {"message": "Request timed out"}})
    mock_genai_client.aio.models.generate_content.side_effect = err_timeout
    with pytest.raises(LLMTimeoutError):
        await provider.generate("hello")

    # 2. Test Connection mapping (status 503 / connection text)
    err_conn = APIError(code=503, response_json={"error": {"message": "connection error"}})
    mock_genai_client.aio.models.generate_content.side_effect = err_conn
    with pytest.raises(LLMConnectionError):
        await provider.generate("hello")

    # 3. Test Bad Request mapping (status 400)
    err_bad = APIError(code=400, response_json={"error": {"message": "invalid arguments"}})
    mock_genai_client.aio.models.generate_content.side_effect = err_bad
    with pytest.raises(LLMResponseError):
        await provider.generate("hello")

    # 4. Test General APIError mapping
    err_general = APIError(code=500, response_json={"error": {"message": "something went wrong"}})
    mock_genai_client.aio.models.generate_content.side_effect = err_general
    with pytest.raises(LLMException):
        await provider.generate("hello")


@pytest.mark.asyncio
async def test_gemini_missing_api_key(mock_genai_client):
    from app.shared.exceptions import ConfigurationError
    with pytest.raises(ConfigurationError):
        GeminiProvider(api_key="")


@pytest.mark.asyncio
async def test_gemini_health_check(mock_genai_client):
    provider_ok = GeminiProvider(api_key="my-key")
    assert await provider_ok.health_check() is True


def test_gemini_metadata(mock_genai_client):
    provider = GeminiProvider(api_key="my-key", model="my-model")
    meta = provider.get_metadata()
    assert meta["provider"] == "gemini"
    assert meta["model"] == "my-model"
    assert meta["capabilities"]["thinking"] is False


@pytest.mark.asyncio
async def test_gemini_close(mock_genai_client):
    provider = GeminiProvider(api_key="my-key")
    mock_genai_client.aio.aclose = AsyncMock()
    await provider.close()
    mock_genai_client.aio.aclose.assert_called_once()


def test_llm_factory_selection(mock_genai_client):
    with patch.object(settings, "LLM_PROVIDER", "gemini"), patch.object(settings, "GEMINI_API_KEY", "some-key"):
        # Clear factory cached instances to force fresh generation
        LLMFactory._instances.clear()
        provider = LLMFactory.get_provider()
        assert isinstance(provider, GeminiProvider)
        assert provider.api_key == "some-key"
        LLMFactory._instances.clear()
