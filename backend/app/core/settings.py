from typing import Annotated, Literal

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_allowed_origins(v: str | list[str]) -> list[str]:
    """Parses a comma-separated string or array of allowed origins for CORS.

    Args:
        v: The environment variable value representing allowed origins.

    Returns:
        list[str]: Formatted list of origin host strings.

    Raises:
        ValueError: If origin format cannot be parsed.
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
    raise ValueError(f"Invalid allowed origins configuration format: {v}")


class Settings(BaseSettings):
    """Centralized environment-driven settings model using Pydantic Settings.

    Loads configuration settings from environment variables or a local .env file.
    Invalid variable types will raise validation errors and stop server startup.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
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

    # API configurations
    API_V1_PREFIX: str = Field(
        default="/api/v1", description="Routing prefix path for version 1 API controllers."
    )
    ALLOWED_ORIGINS: Annotated[list[str], BeforeValidator(parse_allowed_origins)] = Field(
        default=["http://localhost:3000"],
        description="CORS origins allowed to execute network requests.",
    )

    # Database configurations
    DATABASE_URL: str = Field(
       default="sqlite+aiosqlite:///./data/hospital_demo.db",
       description="Relational database connection string URL.",
    )
    DATABASE_POOL_SIZE: int = Field(
        default=10, description="Max database session connection pool size limit."
    )
    DATABASE_ECHO: bool = Field(
        default=False, description="Log database queries to std log out streams when set."
    )

    # LLM configurations
    LLM_PROVIDER: str = Field(
        default="ollama", description="Active LLM provider name."
    )
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434", description="Ollama local API server endpoint."
    )
    OLLAMA_MODEL: str = Field(
        default="qwen3:8b", description="Target text LLM Qwen series model name."
    )
    OLLAMA_TIMEOUT: float = Field(
        default=30.0, description="Ollama API request timeout in seconds."
    )
    LLM_RETRY_COUNT: int = Field(
        default=3, description="Maximum retries for transient failures."
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

    # SQL safety configurations
    SQL_DIALECT: str = Field(
        default="sqlite", description="Default SQL dialect parsed by safety validation layer."
    )

    # Logging configurations
    LOG_LEVEL: str = Field(default="INFO", description="Minimum log reporting levels.")
