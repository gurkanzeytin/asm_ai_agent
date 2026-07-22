from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest

from app.core.config import settings
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.nvidia import NvidiaProvider, resolve_nvidia_model_profile
from app.llm.provider import LLMFactory
from app.llm.remote_policy import RemoteDataPolicyViolation
from app.llm.schemas import LLMResponse


def _httpx_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    return httpx.Response(status_code=status_code, request=request)


def _chat_completion(
    content: str = "Hello!",
    finish_reason: str = "stop",
    prompt_tokens=10,
    completion_tokens=5,
):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


@pytest.fixture
def mock_openai_client():
    with patch("app.llm.nvidia.openai.AsyncOpenAI") as mock_client_class:
        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = AsyncMock()
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client
        yield mock_client_class, mock_client


class TestNvidiaProviderInitialization:
    def test_missing_api_key_raises_configuration_error(self, mock_openai_client):
        from app.shared.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError):
            NvidiaProvider(api_key="")

    def test_uses_correct_base_url_and_model(self, mock_openai_client):
        mock_client_class, _ = mock_openai_client
        NvidiaProvider(
            api_key="nvapi-test",
            base_url="https://integrate.api.nvidia.com/v1",
            model="deepseek-ai/deepseek-v4-pro",
        )
        mock_client_class.assert_called_once_with(
            api_key="nvapi-test",
            base_url="https://integrate.api.nvidia.com/v1",
            timeout=90.0,
            max_retries=0,
        )

    def test_api_key_never_appears_in_repr(self, mock_openai_client):
        provider = NvidiaProvider(api_key="nvapi-super-secret-value")
        assert "nvapi-super-secret-value" not in repr(provider)

    def test_api_key_never_appears_in_init_log_output(self, mock_openai_client, caplog):
        with caplog.at_level("DEBUG"):
            NvidiaProvider(api_key="nvapi-super-secret-value")
        for record in caplog.records:
            assert "nvapi-super-secret-value" not in record.getMessage()


class TestNvidiaGenerate:
    @pytest.mark.asyncio
    async def test_generate_success(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test", model="deepseek-ai/deepseek-v4-pro", retry_count=0
        )
        mock_client.chat.completions.create.return_value = _chat_completion(content="SELECT 1")

        response = await provider.generate("Generate SQL", think=False)

        assert isinstance(response, LLMResponse)
        assert response.content == "SELECT 1"
        assert response.model == "deepseek-ai/deepseek-v4-pro"
        assert response.prompt_tokens == 10
        assert response.completion_tokens == 5
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_thinking_false_sends_correct_extra_body(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test",
            model="deepseek-ai/deepseek-v4-pro",
            retry_count=0,
            thinking=True,
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=False)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"thinking": False}}

    @pytest.mark.asyncio
    async def test_thinking_defers_to_configured_default(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test",
            model="deepseek-ai/deepseek-v4-pro",
            retry_count=0,
            thinking=True,
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=True)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"thinking": True}}

    @pytest.mark.asyncio
    async def test_system_and_user_messages(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Return JSON", options={"system": "You produce JSON only."})

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["messages"] == [
            {"role": "system", "content": "You produce JSON only."},
            {"role": "user", "content": "Return JSON"},
        ]

    @pytest.mark.asyncio
    async def test_timeout_mapping(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)
        mock_client.chat.completions.create.side_effect = openai.APITimeoutError(
            request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
        )

        with pytest.raises(LLMTimeoutError):
            await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_connection_failure_mapping(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)
        mock_client.chat.completions.create.side_effect = openai.APIConnectionError(
            request=httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
        )

        with pytest.raises(LLMConnectionError):
            await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_rate_limit_mapping(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)
        mock_client.chat.completions.create.side_effect = openai.RateLimitError(
            "Rate limit exceeded", response=_httpx_response(429), body=None
        )

        with pytest.raises(LLMRateLimitError):
            await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_authentication_error_mapping(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)
        mock_client.chat.completions.create.side_effect = openai.AuthenticationError(
            "Invalid API key", response=_httpx_response(401), body=None
        )

        with pytest.raises(LLMAuthenticationError):
            await provider.generate("hello")
        # Distinct from a generic connection failure, but still catchable as one.
        assert issubclass(LLMAuthenticationError, LLMConnectionError)

    @pytest.mark.asyncio
    async def test_empty_response_raises_response_error(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)
        mock_client.chat.completions.create.return_value = _chat_completion(content="")

        with pytest.raises(LLMResponseError):
            await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_no_choices_raises_response_error(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)
        response = MagicMock()
        response.choices = []
        mock_client.chat.completions.create.return_value = response

        with pytest.raises(LLMResponseError):
            await provider.generate("hello")

    @pytest.mark.asyncio
    async def test_transient_error_retries_then_succeeds(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=1)
        mock_client.chat.completions.create.side_effect = [
            openai.APIConnectionError(
                request=httpx.Request(
                    "POST", "https://integrate.api.nvidia.com/v1/chat/completions"
                )
            ),
            _chat_completion(content="Recovered"),
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            response = await provider.generate("hello")

        assert response.content == "Recovered"
        assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_unsafe_patient_payload_rejected(self, mock_openai_client):
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)

        with pytest.raises(RemoteDataPolicyViolation):
            await provider.generate("List patients with HastaAdi = 'Ahmet'")

    @pytest.mark.asyncio
    async def test_safe_aggregate_payload_allowed(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", retry_count=0)
        mock_client.chat.completions.create.return_value = _chat_completion(
            content="SELECT COUNT(*) FROM x"
        )

        response = await provider.generate(
            "Group appointments by department and count them, grouped counts only."
        )
        assert response.content == "SELECT COUNT(*) FROM x"


class TestNvidiaMetadataAndLifecycle:
    def test_get_metadata(self, mock_openai_client):
        provider = NvidiaProvider(
            api_key="nvapi-test", model="my-model", timeout=45.0, retry_count=2
        )
        meta = provider.get_metadata()
        assert meta["provider"] == "nvidia"
        assert meta["model"] == "my-model"
        assert meta["capabilities"]["remote"] is True
        assert meta["capabilities"]["streaming"] is False

    @pytest.mark.asyncio
    async def test_close(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test")
        await provider.close()
        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_generate_raises_not_implemented(self, mock_openai_client):
        provider = NvidiaProvider(api_key="nvapi-test")
        with pytest.raises(NotImplementedError):
            async for _ in provider.stream_generate("Test"):
                pass

    @pytest.mark.asyncio
    async def test_embed_raises_not_implemented(self, mock_openai_client):
        provider = NvidiaProvider(api_key="nvapi-test")
        with pytest.raises(NotImplementedError):
            await provider.embed("text")

    @pytest.mark.asyncio
    async def test_health_check(self, mock_openai_client):
        provider = NvidiaProvider(api_key="nvapi-test")
        assert await provider.health_check() is True


class TestNvidiaModelProfiles:
    """Covers goal E: multi-model NVIDIA support via profiles, no per-model provider."""

    def test_deepseek_profile_unchanged(self, mock_openai_client):
        """DeepSeek model selection keeps its existing thinking-capable request shape."""
        provider = NvidiaProvider(api_key="nvapi-test", model="deepseek-ai/deepseek-v4-pro")
        assert provider.profile.supports_thinking is True
        assert provider.profile.model_id == "deepseek-ai/deepseek-v4-pro"

    def test_glm_model_selection_works(self, mock_openai_client):
        """GLM-5.2 can be selected through the same provider/client, no separate class."""
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2")
        assert provider.model == "z-ai/glm-5.2"
        assert provider.profile.supports_thinking is False

    @pytest.mark.asyncio
    async def test_configured_model_passed_to_client(self, mock_openai_client):
        """The exact configured model string reaches AsyncOpenAI.chat.completions.create."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2", retry_count=0)
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=False)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "z-ai/glm-5.2"

    @pytest.mark.asyncio
    async def test_deepseek_thinking_extra_body_only_for_deepseek(self, mock_openai_client):
        """DeepSeek-specific extra_body is sent for DeepSeek, unaffected by this change."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test", model="deepseek-ai/deepseek-v4-pro", retry_count=0, thinking=True
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=True)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"thinking": True}}

    @pytest.mark.asyncio
    async def test_glm_never_receives_deepseek_extra_body(self, mock_openai_client):
        """GLM-5.2 must not receive chat_template_kwargs.thinking, regardless of think= flag."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2", retry_count=0)
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=True)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] is None

    @pytest.mark.asyncio
    async def test_glm_defaults_applied_without_overrides(self, mock_openai_client):
        """With no per-call overrides, GLM-5.2 uses temperature=1, top_p=1 per NVIDIA docs."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2", retry_count=0)
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 1.0
        assert call_kwargs["top_p"] == 1.0

    @pytest.mark.asyncio
    async def test_glm_per_call_overrides_still_work(self, mock_openai_client):
        """Per-call temperature/top_p/max_tokens overrides win over GLM's profile defaults."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2", retry_count=0)
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate(
            "Question", options={"temperature": 0.3, "top_p": 0.5, "max_tokens": 32}
        )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["top_p"] == 0.5
        assert call_kwargs["max_tokens"] == 32

    @pytest.mark.asyncio
    async def test_remote_data_policy_applies_to_glm_too(self, mock_openai_client):
        """Remote data policy screening is model-agnostic; GLM gets the same guard as DeepSeek."""
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2", retry_count=0)

        with pytest.raises(RemoteDataPolicyViolation):
            await provider.generate("List patients with HastaAdi = 'Ahmet'")

    def test_resolve_profile_defaults_unknown_model_to_deepseek_shape(self):
        """An unrecognized NVIDIA model id falls back to the DeepSeek-shaped profile."""
        profile = resolve_nvidia_model_profile("some-future-nvidia/model")
        assert profile.supports_thinking is True

    def test_glm_model_id_never_collapsed_to_generic_nvidia_label(self, mock_openai_client):
        """Evaluation/logging metadata must record the exact model id, not a generic label."""
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2")
        meta = provider.get_metadata()
        assert meta["model"] == "z-ai/glm-5.2"
        assert meta["provider"] == "nvidia"


class TestNemotronProfile:
    """Covers Nemotron 3 Ultra: the active remote model for complex insight generation."""

    def test_resolve_profile_exact_model_id(self):
        profile = resolve_nvidia_model_profile("nvidia/nemotron-3-ultra-550b-a55b")
        assert profile.model_id == "nvidia/nemotron-3-ultra-550b-a55b"
        assert profile.supports_thinking is True
        assert profile.thinking_key == "enable_thinking"
        assert profile.default_temperature == 0.1
        assert profile.default_top_p == 0.95
        assert profile.recommended_max_tokens == 1024

    def test_provider_resolves_nemotron_profile(self, mock_openai_client):
        provider = NvidiaProvider(api_key="nvapi-test", model="nvidia/nemotron-3-ultra-550b-a55b")
        assert provider.model == "nvidia/nemotron-3-ultra-550b-a55b"
        assert provider.profile.thinking_key == "enable_thinking"

    @pytest.mark.asyncio
    async def test_normal_path_sends_enable_thinking_false(self, mock_openai_client):
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test", model="nvidia/nemotron-3-ultra-550b-a55b", retry_count=0
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Summarize the trend", think=False)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
        assert call_kwargs["model"] == "nvidia/nemotron-3-ultra-550b-a55b"

    @pytest.mark.asyncio
    async def test_thinking_disabled_by_default_even_when_think_true(self, mock_openai_client):
        """Without an explicit `thinking=True` provider option, Nemotron stays off
        (NVIDIA_THINKING default False)."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test", model="nvidia/nemotron-3-ultra-550b-a55b", retry_count=0
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=True)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}

    @pytest.mark.asyncio
    async def test_explicit_thinking_mode_opt_in(self, mock_openai_client):
        """Complex reasoning mode is only reachable through an explicit provider option."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test",
            model="nvidia/nemotron-3-ultra-550b-a55b",
            retry_count=0,
            thinking=True,
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Deep multi-metric analysis", think=True)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}

    @pytest.mark.asyncio
    async def test_never_receives_deepseek_thinking_key(self, mock_openai_client):
        """Profile isolation: Nemotron uses enable_thinking, never DeepSeek's `thinking` key."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test", model="nvidia/nemotron-3-ultra-550b-a55b", retry_count=0
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=False)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "thinking" not in call_kwargs["extra_body"]["chat_template_kwargs"]

    @pytest.mark.asyncio
    async def test_deepseek_never_receives_nemotron_thinking_key(self, mock_openai_client):
        """Profile isolation the other way: DeepSeek never sees enable_thinking."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test", model="deepseek-ai/deepseek-v4-pro", retry_count=0
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=False)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "enable_thinking" not in call_kwargs["extra_body"]["chat_template_kwargs"]

    @pytest.mark.asyncio
    async def test_glm_never_receives_nemotron_or_deepseek_thinking_keys(self, mock_openai_client):
        """Profile isolation: GLM never receives any thinking-mode extra_body at all."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2", retry_count=0)
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question", think=True)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["extra_body"] is None

    def test_get_metadata_reports_thinking_key(self, mock_openai_client):
        provider = NvidiaProvider(api_key="nvapi-test", model="nvidia/nemotron-3-ultra-550b-a55b")
        meta = provider.get_metadata()
        assert meta["model"] == "nvidia/nemotron-3-ultra-550b-a55b"
        assert meta["model_profile"]["thinking_key"] == "enable_thinking"

    def test_glm_metadata_thinking_key_is_none(self, mock_openai_client):
        """GLM doesn't support thinking at all, so thinking_key must not be reported."""
        provider = NvidiaProvider(api_key="nvapi-test", model="z-ai/glm-5.2")
        meta = provider.get_metadata()
        assert meta["model_profile"]["thinking_key"] is None

    @pytest.mark.asyncio
    async def test_remote_data_policy_applies_to_nemotron(self, mock_openai_client):
        provider = NvidiaProvider(
            api_key="nvapi-test", model="nvidia/nemotron-3-ultra-550b-a55b", retry_count=0
        )
        with pytest.raises(RemoteDataPolicyViolation):
            await provider.generate("List patients with HastaAdi = 'Ahmet'")

    @pytest.mark.asyncio
    async def test_no_stream_kwarg_sent_defaults_to_false(self, mock_openai_client):
        """No `stream` kwarg is passed to the SDK, so it defaults to non-streaming."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test", model="nvidia/nemotron-3-ultra-550b-a55b", retry_count=0
        )
        mock_client.chat.completions.create.return_value = _chat_completion()

        await provider.generate("Question")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "stream" not in call_kwargs or call_kwargs["stream"] is False

    @pytest.mark.asyncio
    async def test_deepseek_404_style_failure_maps_to_response_error(self, mock_openai_client):
        """DeepSeek's current NVIDIA-side 404 must surface as a normal, catchable
        LLMResponseError (via BadRequestError/APIStatusError mapping), not crash
        the provider — this is what lets InsightEngine's fallback handle it."""
        _, mock_client = mock_openai_client
        provider = NvidiaProvider(
            api_key="nvapi-test", model="deepseek-ai/deepseek-v4-pro", retry_count=0
        )
        not_found_response = _httpx_response(404)
        mock_client.chat.completions.create.side_effect = openai.NotFoundError(
            "Not Found", response=not_found_response, body=None
        )

        with pytest.raises(LLMResponseError):
            await provider.generate("Question")


class TestNvidiaFactorySelection:
    def test_nvidia_selected_when_configured(self, mock_openai_client):
        with patch.object(settings, "LLM_PROVIDER", "nvidia"):
            with patch.object(settings, "NVIDIA_API_KEY") as mock_key:
                mock_key.get_secret_value.return_value = "nvapi-configured-key"
                LLMFactory._instances.clear()
                provider = LLMFactory.get_provider()
                assert isinstance(provider, NvidiaProvider)
                LLMFactory._instances.clear()

    def test_ollama_remains_default_llm_provider(self):
        from app.core.settings import Settings
        from app.llm.ollama import OllamaProvider

        assert Settings.model_fields["LLM_PROVIDER"].default == "ollama"
        LLMFactory._instances.clear()
        provider = LLMFactory.get_provider("ollama")
        assert isinstance(provider, OllamaProvider)
        LLMFactory._instances.clear()
