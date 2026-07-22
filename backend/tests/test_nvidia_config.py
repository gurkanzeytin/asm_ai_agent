import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def _base_settings_kwargs() -> dict:
    """Minimal kwargs so Settings() constructs without touching the real .env file."""
    return {
        "_env_file": None,
        "DB_SERVER": "test-server",
        "DB_DATABASE": "test-db",
        "DB_DRIVER": "ODBC Driver 18 for SQL Server",
    }


class TestNvidiaSettingsValidation:
    def test_nvidia_api_key_not_required_for_ollama_provider(self):
        settings = Settings(LLM_PROVIDER="ollama", **_base_settings_kwargs())
        assert settings.LLM_PROVIDER == "ollama"
        assert settings.NVIDIA_API_KEY.get_secret_value() == ""

    def test_nvidia_api_key_required_when_provider_is_nvidia(self):
        with pytest.raises(ValidationError, match="NVIDIA_API_KEY"):
            Settings(LLM_PROVIDER="nvidia", NVIDIA_API_KEY="", **_base_settings_kwargs())

    def test_nvidia_api_key_accepted_when_provider_is_nvidia(self):
        settings = Settings(
            LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nvapi-real-key", **_base_settings_kwargs()
        )
        assert settings.NVIDIA_API_KEY.get_secret_value() == "nvapi-real-key"

    def test_nvidia_defaults(self):
        settings = Settings(
            LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nvapi-real-key", **_base_settings_kwargs()
        )
        assert settings.NVIDIA_BASE_URL == "https://integrate.api.nvidia.com/v1"
        assert settings.NVIDIA_MODEL == "deepseek-ai/deepseek-v4-pro"
        assert settings.NVIDIA_TIMEOUT_SECONDS == 90.0
        assert settings.NVIDIA_MAX_RETRIES == 1
        assert settings.NVIDIA_MAX_TOKENS == 2048
        assert settings.NVIDIA_TEMPERATURE == 0.1
        assert settings.NVIDIA_TOP_P == 0.95
        assert settings.NVIDIA_THINKING is False

    def test_nvidia_api_key_never_appears_in_repr(self):
        settings = Settings(
            LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nvapi-super-secret", **_base_settings_kwargs()
        )
        assert "nvapi-super-secret" not in repr(settings)
        assert "nvapi-super-secret" not in str(settings)

    def test_nvidia_api_key_never_appears_in_validation_error_text(self):
        with pytest.raises(ValidationError) as exc_info:
            Settings(LLM_PROVIDER="nvidia", NVIDIA_API_KEY="", **_base_settings_kwargs())
        assert "nvapi" not in str(exc_info.value)

    def test_insight_routing_defaults(self):
        """Insight routing defaults match the required routing policy: routing and
        deterministic generation both on, local=ollama, remote=nvidia, threshold=3."""
        settings = Settings(**_base_settings_kwargs())
        assert settings.INSIGHT_ROUTING_ENABLED is True
        assert settings.INSIGHT_DETERMINISTIC_ENABLED is True
        assert settings.INSIGHT_LOCAL_PROVIDER == "ollama"
        assert settings.INSIGHT_REMOTE_PROVIDER == "nvidia"
        assert settings.INSIGHT_REMOTE_COMPLEXITY_THRESHOLD == 3


class TestRootEnvFileResolution:
    """The root .env file (not backend/.env) is the canonical environment source."""

    def test_env_file_is_anchored_to_repo_root(self):
        from pathlib import Path

        from app.core.settings import _REPO_ROOT_ENV_FILE

        expected = Path(__file__).resolve().parents[2] / ".env"
        assert _REPO_ROOT_ENV_FILE == expected
        assert _REPO_ROOT_ENV_FILE.name == ".env"
        # The example file documenting this contract lives alongside the real one.
        assert (_REPO_ROOT_ENV_FILE.parent / ".env.example").exists()

    def test_settings_model_config_uses_repo_root_env_file(self):
        from app.core.settings import _REPO_ROOT_ENV_FILE, Settings

        assert Settings.model_config["env_file"] == _REPO_ROOT_ENV_FILE

    def test_backend_local_env_is_not_the_configured_source(self):
        """Regression guard: settings must not silently fall back to backend/.env."""
        from pathlib import Path

        from app.core.settings import _REPO_ROOT_ENV_FILE

        backend_env = Path(__file__).resolve().parents[1] / ".env"
        assert _REPO_ROOT_ENV_FILE != backend_env
