from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qsl, quote_plus, unquote_plus, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, BeforeValidator, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Anchored to the repository root (backend/app/core/settings.py -> repo root),
# not the process working directory. `env_file=".env"` alone resolves against
# the CWD, which silently picks up a different .env when the app is launched
# from backend/ (per README) instead of the repo root where .env.example lives.
_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def parse_comma_separated_list(v: str | list[str]) -> list[str]:
    """Parses a comma-separated string or JSON array environment value into a list.

    Args:
        v: The environment variable value (comma-separated string, JSON array, or list).

    Returns:
        list[str]: Parsed list of stripped string items.

    Raises:
        ValueError: If the value format cannot be parsed.
    """
    if isinstance(v, str):
        if not v.strip():
            return []
        if v.startswith("["):
            import json

            try:
                return json.loads(v)
            except Exception:
                pass
        return [item.strip() for item in v.split(",") if item.strip()]
    elif isinstance(v, list):
        return v
    raise ValueError(f"Invalid comma-separated list configuration format: {v}")


# Backwards-compatible alias retained for existing imports.
parse_allowed_origins = parse_comma_separated_list


class Settings(BaseSettings):
    """Centralized environment-driven settings model using Pydantic Settings.

    Loads configuration settings from environment variables or a local .env file.
    Invalid variable types will raise validation errors and stop server startup.
    """

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV_FILE,
        env_ignore_empty=True,
        extra="ignore",
    )

    # Application settings
    APP_NAME: str = Field(
        default="ASM AI Agent", description="The human-readable name of the application."
    )
    APP_VERSION: str = Field(
        default="1.0.0", description="The semantic version of the application."
    )
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development", description="The environment stage the system is active in."
    )
    DEBUG: bool = Field(
        default=True, description="Indicates whether debugger execution configurations are active."
    )
    INTENT_CONFIDENCE_THRESHOLD: float = Field(
        default=0.6,
        description="Threshold below which any intent classification defaults to DATABASE_QUERY."
    )

    # API configurations
    API_V1_PREFIX: str = Field(
        default="/api/v1", description="Routing prefix path for version 1 API controllers."
    )
    ALLOWED_ORIGINS: Annotated[list[str], BeforeValidator(parse_allowed_origins)] = Field(
        default=["http://localhost:3000", "http://localhost:3001"],
        description="CORS origins allowed to execute network requests.",
    )

    # Database configurations — Microsoft SQL Server is the only runtime database.
    # The async SQLAlchemy URL is constructed from the DB_* parts below unless an
    # explicit DATABASE_URL override is provided. Windows Authentication is used:
    # the identity of the process running the backend, never a username/password.
    DB_SERVER: str = Field(
        default="ASMPSHISBCK2", description="SQL Server host name (default instance)."
    )
    DB_DATABASE: str = Field(default="PusulaComed", description="Target SQL Server database name.")
    DB_DRIVER: str = Field(
        default="ODBC Driver 18 for SQL Server",
        description="Installed Microsoft ODBC driver name used by pyodbc/aioodbc.",
    )
    DB_TRUSTED_CONNECTION: bool = Field(
        default=True,
        description="Use Windows Authentication (integrated security) for the connection.",
    )
    DB_TRUST_SERVER_CERTIFICATE: bool = Field(
        default=True, description="Trust the SQL Server TLS certificate (internal network)."
    )
    DATABASE_URL: str = Field(
        default="",
        description="Optional explicit SQLAlchemy async URL override (mssql+aioodbc only). "
        "Left empty, it is constructed from DB_SERVER/DB_DATABASE/DB_DRIVER.",
    )
    DATABASE_POOL_SIZE: int = Field(
        default=10, description="Max database session connection pool size limit."
    )
    DATABASE_ECHO: bool = Field(
        default=False, description="Log database queries to std log out streams when set."
    )
    DATABASE_SCHEMA: str = Field(
        default="dbo",
        validation_alias=AliasChoices("DATABASE_SCHEMA", "DB_SCHEMA"),
        description="SQL Server schema containing the allowed object(s).",
    )
    DATABASE_ALLOWED_OBJECTS: Annotated[
        list[str], NoDecode, BeforeValidator(parse_comma_separated_list)
    ] = Field(
        default=["dbo.vw_RandevuRaporu"],
        validation_alias=AliasChoices("DATABASE_ALLOWED_OBJECTS", "DB_OBJECT"),
        description="Comma-separated whitelist of queryable objects. Generated SQL may only "
        "read from these objects; everything else is rejected.",
    )
    DATABASE_CONNECT_TIMEOUT: int = Field(
        default=15, description="Database connection/login timeout in seconds."
    )
    DATABASE_QUERY_TIMEOUT: int = Field(
        default=60, description="Database query execution timeout in seconds where supported."
    )
    DATABASE_MAX_PAGE_SIZE: int = Field(
        default=1000, description="Maximum allowed page size for paginated query execution."
    )

    # LLM configurations
    LLM_PROVIDER: str = Field(
        default="ollama", description="Active LLM provider name."
    )
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434", description="Ollama local API server endpoint."
    )
    OLLAMA_MODEL: str = Field(
        default="qwen3:8b",
        description="Ollama model name. Use a smaller model (e.g. qwen2.5:3b) for faster development inference; qwen3:8b for production quality.",
    )
    OLLAMA_EMBEDDING_MODEL: str = Field(
        default="nomic-embed-text",
        description="Embedding model used for semantic retrieval.",
    )
    OLLAMA_TIMEOUT: float = Field(
        default=30.0, description="Ollama API request timeout in seconds."
    )
    LLM_RETRY_COUNT: int = Field(
        default=3, description="Maximum retries for transient failures."
    )
    GEMINI_API_KEY: str = Field(
        default="", description="Google Gemini API key."
    )
    GEMINI_MODEL: str = Field(
        default="gemini-2.5-flash", description="Active Gemini model name."
    )
    NVIDIA_API_KEY: SecretStr = Field(
        default=SecretStr(""),
        description="NVIDIA NIM (OpenAI-compatible) API key. Required only when "
        "LLM_PROVIDER=nvidia. Wrapped in SecretStr so it never appears in repr(), "
        "str(), logs, or exception text.",
    )
    NVIDIA_BASE_URL: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="NVIDIA OpenAI-compatible API base URL.",
    )
    NVIDIA_MODEL: str = Field(
        default="deepseek-ai/deepseek-v4-pro",
        description="Active NVIDIA-hosted model name, e.g. 'nvidia/nemotron-3-ultra-550b-a55b' "
        "(the verified remote model for complex insight generation, see "
        "app.insights.routing), 'deepseek-ai/deepseek-v4-pro', or 'z-ai/glm-5.2'. Per-model "
        "request defaults (temperature, top_p, thinking-mode support/key) are derived "
        "automatically in app.llm.nvidia.resolve_nvidia_model_profile; any model id not "
        "explicitly profiled falls back to DeepSeek's request shape. The deployed default is "
        "set via NVIDIA_MODEL in the root .env file, not this in-code default.",
    )
    NVIDIA_TIMEOUT_SECONDS: float = Field(
        default=90.0, description="NVIDIA API request timeout in seconds."
    )
    NVIDIA_MAX_RETRIES: int = Field(
        default=1, description="Maximum retries for transient NVIDIA API failures."
    )
    NVIDIA_MAX_TOKENS: int = Field(
        default=2048, description="Maximum completion tokens requested from the NVIDIA model."
    )
    NVIDIA_TEMPERATURE: float = Field(
        default=0.1, description="Sampling temperature for the NVIDIA model."
    )
    NVIDIA_TOP_P: float = Field(
        default=0.95, description="Nucleus sampling top_p for the NVIDIA model."
    )
    NVIDIA_THINKING: bool = Field(
        default=False,
        description="Requests NVIDIA-compatible 'thinking' mode via chat_template_kwargs "
        "when supported by the model.",
    )
    OBSERVATION_LLM_WORDING: bool = Field(
        default=False,
        description=(
            "Use the LLM to reword deterministic observations into natural language. "
            "Facts always come from templates; the LLM never adds or removes observations."
        ),
    )

    # Insight generation routing — deterministic / local (Ollama) / remote (NVIDIA).
    # Reuses NVIDIA_*/OLLAMA_* credentials and model settings above; these only
    # control the routing decision, never a separate credential set.
    INSIGHT_ROUTING_ENABLED: bool = Field(
        default=True,
        description="Enables complexity-based routing for insight generation. When false, "
        "routing always selects the local provider (deterministic templates remain "
        "available if INSIGHT_DETERMINISTIC_ENABLED is also true).",
    )
    INSIGHT_DETERMINISTIC_ENABLED: bool = Field(
        default=True,
        description="Enables the deterministic (no-LLM) insight path for simple analysis "
        "families (count, distribution, top-N, ratio, min/max, empty result, etc.).",
    )
    INSIGHT_LOCAL_PROVIDER: str = Field(
        default="ollama", description="Provider name used for the local insight-routing leg."
    )
    INSIGHT_REMOTE_PROVIDER: str = Field(
        default="nvidia", description="Provider name used for the remote insight-routing leg."
    )
    INSIGHT_REMOTE_COMPLEXITY_THRESHOLD: int = Field(
        default=3,
        description="Minimum computed complexity score (see app.insights.routing) required "
        "to route an insight to the remote provider instead of the local one. Only reached "
        "for analyses that already failed deterministic candidacy.",
    )
    INSIGHT_DETERMINISTIC_MAX_ROWS: int = Field(
        default=20,
        description="Maximum result size (row count) still eligible for deterministic insight "
        "generation for one-dimensional categorical groupings and basic period comparisons. "
        "Larger results are not 'simple' by size alone, regardless of which rules fired.",
    )

    # Conversational context / chat-memory configurations
    CHAT_MEMORY_MAX_TURNS: int = Field(
        default=8,
        description="Sliding window size: number of most-recent turns retained per session.",
    )
    CHAT_MEMORY_TTL_SECONDS: float = Field(
        default=1800.0,
        description="Session inactivity expiry (seconds). A session idle longer than this "
        "starts fresh on its next request — the deterministic proxy for 'new conversation' "
        "absent an explicit frontend signal.",
    )

    # Database Intelligence configurations
    SCHEMA_CACHE_ENABLED: bool = Field(
        default=True, description="Enable in-memory caching of the database schema."
    )
    SCHEMA_CACHE_TTL: float = Field(
        default=3600.0, description="Schema cache expiration Time-To-Live in seconds."
    )
    AUTO_REFRESH_SCHEMA: bool = Field(
        default=True, description="Automatically inspect database to refresh cache on expiration."
    )
    SCHEMA_MAX_TABLES: int = Field(
        default=5,
        description="Maximum number of tables included in LLM context during schema fallback. Reduce to shrink prompt size.",
    )
    SCHEMA_MAX_COLUMNS: int = Field(
        default=15,
        description="Maximum columns per table included in LLM context during schema fallback. PK and FK columns are always preserved.",
    )
    SCHEMA_TOKEN_BUDGET: int = Field(
        default=1500,
        description="Configurable token budget for rendering schema context in prompts.",
    )
    SCHEMA_GRAPH_MAX_DEPTH: int = Field(
        default=2,
        description="Maximum traversal depth for foreign key expansion graph search.",
    )

    # SQL safety configurations
    SQL_DIALECT: str = Field(
        default="tsql",
        description="SQL dialect parsed by the safety validation layer "
        "('tsql' for SQL Server).",
    )

    # Report configurations
    REPORT_MAX_ROWS: int = Field(
        default=100,
        description="Maximum number of query result rows to include in the report prompt context.",
    )
    REPORT_ANALYTICAL_ROW_THRESHOLD: int = Field(
        default=20,
        description="Row count threshold above which report generation uses LLM analytical summarization.",
    )

    # Logging configurations
    LOG_LEVEL: str = Field(default="INFO", description="Minimum log reporting levels.")

    def build_odbc_connection_string(self) -> str:
        """Builds the ODBC connection string from the DB_* parts.

        Never logged: treat the returned value as sensitive configuration.
        """
        odbc = (
            f"DRIVER={{{self.DB_DRIVER}}};"
            f"SERVER={self.DB_SERVER};"
            f"DATABASE={self.DB_DATABASE};"
        )
        if self.DB_TRUSTED_CONNECTION:
            odbc += "Trusted_Connection=yes;"
        # ODBC Driver 18 defaults to encryption, but make it explicit so the
        # effective transport policy is visible and testable at the ODBC layer.
        odbc += "Encrypt=yes;"
        if self.ENVIRONMENT == "development" and self.DB_TRUST_SERVER_CERTIFICATE:
            odbc += "TrustServerCertificate=yes;"
        return odbc

    def _apply_development_odbc_options(self, database_url: str) -> str:
        """Adds development-only ODBC TLS overrides without logging URL values."""
        parts = urlsplit(database_url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        odbc_index = next(
            (index for index, (key, _value) in enumerate(query) if key.lower() == "odbc_connect"),
            None,
        )
        if odbc_index is not None:
            odbc = unquote_plus(query[odbc_index][1])
            entries = [
                (key.strip(), value.strip())
                for entry in odbc.split(";")
                if entry.strip() and "=" in entry
                for key, value in [entry.split("=", 1)]
                if key.strip().lower() not in {"encrypt", "trustservercertificate"}
            ]
            entry_keys = {key.lower() for key, _value in entries}
            if self.DB_TRUSTED_CONNECTION and not {"uid", "user", "pwd", "password"} & entry_keys:
                entries.append(("Trusted_Connection", "yes"))
            entries.extend([("Encrypt", "yes"), ("TrustServerCertificate", "yes")])
            query[odbc_index] = (
                query[odbc_index][0],
                ";".join(f"{key}={value}" for key, value in entries) + ";",
            )
        else:
            query = [
                (key, value)
                for key, value in query
                if key.lower() not in {"encrypt", "trustservercertificate"}
            ]
            query_keys = {key.lower() for key, _value in query}
            if (
                self.DB_TRUSTED_CONNECTION
                and not {"uid", "user", "pwd", "password"} & query_keys
                and not parts.username
                and "trusted_connection" not in query_keys
            ):
                query.append(("Trusted_Connection", "yes"))
            query.extend([("Encrypt", "yes"), ("TrustServerCertificate", "yes")])
        encoded_query = urlencode(query)
        # ``urlunsplit`` collapses the empty netloc in ``mssql+aioodbc:///``
        # to two slashes, which SQLAlchemy rejects for an odbc_connect URL.
        if not parts.netloc and parts.path.startswith("/"):
            rebuilt = f"{parts.scheme}://{parts.path}"
            if encoded_query:
                rebuilt += f"?{encoded_query}"
            return rebuilt
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, encoded_query, parts.fragment)
        )

    @model_validator(mode="after")
    def _validate_nvidia_provider_requirements(self) -> "Settings":
        """Requires NVIDIA_API_KEY only when NVIDIA is the active LLM provider.

        Other provider configurations (Ollama, Gemini) are untouched by this check,
        so switching LLM_PROVIDER back to 'ollama' never requires an NVIDIA key.
        """
        provider_is_nvidia = self.LLM_PROVIDER.strip().lower() == "nvidia"
        if provider_is_nvidia and not self.NVIDIA_API_KEY.get_secret_value():
            raise ValueError(
                "LLM_PROVIDER=nvidia requires NVIDIA_API_KEY to be set in the "
                "environment or .env file."
            )
        return self

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        """Constructs and validates the SQL Server connection URL at startup."""
        if not self.DATABASE_URL:
            missing = [
                name
                for name, value in (
                    ("DB_SERVER", self.DB_SERVER),
                    ("DB_DATABASE", self.DB_DATABASE),
                    ("DB_DRIVER", self.DB_DRIVER),
                )
                if not str(value).strip()
            ]
            if missing:
                raise ValueError(
                    f"Cannot construct the SQL Server connection URL: missing required "
                    f"database settings {', '.join(missing)}. Set them in the environment "
                    f"or .env file."
                )
            self.DATABASE_URL = (
                f"mssql+aioodbc:///?odbc_connect={quote_plus(self.build_odbc_connection_string())}"
            )
        elif not self.DATABASE_URL.startswith("mssql+aioodbc"):
            raise ValueError(
                "DATABASE_URL must use the async SQL Server scheme 'mssql+aioodbc://...'. "
                "Microsoft SQL Server is the only supported runtime database."
            )
        if self.ENVIRONMENT == "development":
            self.DATABASE_URL = self._apply_development_odbc_options(self.DATABASE_URL)
        return self
