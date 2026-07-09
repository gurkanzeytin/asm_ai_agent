import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.llm import LLMFactory, LLMResponse, OllamaProvider
from app.llm.exceptions import LLMConnectionError, LLMResponseError, LLMTimeoutError


@pytest.mark.asyncio
async def test_provider_initialization():
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", timeout=15.0, retry_count=2
    )
    assert provider.base_url == "http://test-ollama:11434"
    assert provider.model == "test-model"
    assert provider.timeout == 15.0
    assert provider.retry_count == 2
    await provider.close()


@pytest.mark.asyncio
async def test_factory_creation():
    # Clear any cached instances first
    await LLMFactory.clear_providers()

    # Get provider using default configuration
    provider1 = LLMFactory.get_provider()
    assert isinstance(provider1, OllamaProvider)

    # Get provider again - should return the exact same instance (singleton caching)
    provider2 = LLMFactory.get_provider("ollama")
    assert provider1 is provider2

    # Check that unsupported provider raises ValueError
    with pytest.raises(ValueError):
        LLMFactory.get_provider("openai")

    await LLMFactory.clear_providers()


@pytest.mark.asyncio
async def test_successful_mocked_generation(caplog):
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", retry_count=0
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "Hello World!",
        "prompt_eval_count": 10,
        "eval_count": 20,
    }

    with patch.object(provider._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with caplog.at_level("INFO"):
            response = await provider.generate("Test prompt")

            assert isinstance(response, LLMResponse)
            assert response.content == "Hello World!"
            assert response.model == "test-model"
            assert response.latency_ms > 0
            assert response.prompt_tokens == 10
            assert response.completion_tokens == 20

            # Check logging execution
            log_messages = [rec.message for rec in caplog.records]
            assert "LLM request completed successfully" in log_messages

            # Check metadata was logged in extra attributes
            log_record = next(
                rec
                for rec in caplog.records
                if rec.message == "LLM request completed successfully"
            )
            assert log_record.model_name == "test-model"
            assert log_record.provider == "ollama"
            assert log_record.prompt_length == len("Test prompt")
            assert log_record.response_length == len("Hello World!")
            assert hasattr(log_record, "latency")
            assert hasattr(log_record, "request_timestamp")

    await provider.close()


@pytest.mark.asyncio
async def test_timeout_handling():
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", retry_count=0
    )

    with patch.object(provider._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("Timeout")

        with pytest.raises(LLMTimeoutError):
            await provider.generate("Test prompt")

    await provider.close()


@pytest.mark.asyncio
async def test_connection_failure():
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", retry_count=0
    )

    with patch.object(provider._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(LLMConnectionError):
            await provider.generate("Test prompt")

    await provider.close()


@pytest.mark.asyncio
async def test_response_validation_http_error():
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", retry_count=0
    )

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error", request=MagicMock(), response=mock_response
    )

    with patch.object(provider._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        with pytest.raises(LLMResponseError):
            await provider.generate("Test prompt")

    await provider.close()


@pytest.mark.asyncio
async def test_health_check_success():
    provider = OllamaProvider(base_url="http://test-ollama:11434", model="test-model")

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch.object(provider._client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        res = await provider.health_check()
        assert res is True
        mock_get.assert_called_once_with("http://test-ollama:11434/api/tags")

    await provider.close()


@pytest.mark.asyncio
async def test_health_check_failure():
    provider = OllamaProvider(base_url="http://test-ollama:11434", model="test-model")

    with patch.object(provider._client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Network down")

        res = await provider.health_check()
        assert res is False

    await provider.close()


@pytest.mark.asyncio
async def test_stream_generate_raises_not_implemented():
    provider = OllamaProvider(base_url="http://test-ollama:11434", model="test-model")

    with pytest.raises(NotImplementedError):
        async for _ in provider.stream_generate("Test"):
            pass

    await provider.close()


@pytest.mark.asyncio
async def test_get_metadata():
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", timeout=12.0, retry_count=5
    )
    meta = provider.get_metadata()
    assert meta["provider"] == "ollama"
    assert meta["model"] == "test-model"
    assert meta["timeout"] == 12.0
    assert meta["retry_count"] == 5
    assert meta["capabilities"]["streaming"] is False
    assert meta["capabilities"]["text_generation"] is True
    await provider.close()


@pytest.mark.asyncio
async def test_transient_retries_success():
    # Setup provider with 2 retries (3 attempts total)
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", retry_count=2
    )

    mock_success = MagicMock()
    mock_success.status_code = 200
    mock_success.json.return_value = {
        "response": "Recovered!",
        "prompt_eval_count": 5,
        "eval_count": 5,
    }

    with patch.object(provider._client, "post", new_callable=AsyncMock) as mock_post:
        # First attempt fails with ConnectError, second attempt succeeds
        mock_post.side_effect = [httpx.ConnectError("Failed once"), mock_success]

        # Mock asyncio.sleep to avoid waiting during tests
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            response = await provider.generate("Retry test")
            assert response.content == "Recovered!"
            assert mock_post.call_count == 2
            mock_sleep.assert_called_once_with(0.5)

    await provider.close()


@pytest.mark.asyncio
async def test_transient_retries_max_exceeded():
    # Setup provider with 1 retry (2 attempts total)
    provider = OllamaProvider(
        base_url="http://test-ollama:11434", model="test-model", retry_count=1
    )

    with patch.object(provider._client, "post", new_callable=AsyncMock) as mock_post:
        # Both attempts fail with TimeoutException
        mock_post.side_effect = [
            httpx.TimeoutException("Timeout 1"),
            httpx.TimeoutException("Timeout 2"),
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMTimeoutError):
                await provider.generate("Retry test fail")
            assert mock_post.call_count == 2
            mock_sleep.assert_called_once_with(0.5)

    await provider.close()


@pytest.mark.asyncio
async def test_ollama_missing_base_url():
    from app.shared.exceptions import ConfigurationError
    with patch.object(settings, "OLLAMA_BASE_URL", ""):
        with pytest.raises(ConfigurationError):
            OllamaProvider(base_url="")
