from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("GRANTORA_ENV", "GATEWAY_ENV"),
    )
    public_base_url: str = Field(
        default="http://localhost:9080",
        validation_alias=AliasChoices("GRANTORA_PUBLIC_BASE_URL", "GATEWAY_PUBLIC_BASE_URL"),
    )
    bind_addr: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("GRANTORA_BIND_ADDR", "GATEWAY_BIND_ADDR"),
    )
    port: int = Field(default=8080, validation_alias=AliasChoices("GRANTORA_PORT", "GATEWAY_PORT"))
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("GRANTORA_LOG_LEVEL", "GATEWAY_LOG_LEVEL", "LOG_LEVEL"),
    )
    json_logs: bool = Field(
        default=True,
        validation_alias=AliasChoices("GRANTORA_JSON_LOGS", "GATEWAY_JSON_LOGS"),
    )
    database_url: str = Field(
        default="postgresql+psycopg://grantora:grantora@postgres:5432/grantora",
        validation_alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=10, validation_alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=20, validation_alias="DATABASE_MAX_OVERFLOW")
    migrations_auto_run: bool = Field(default=True, validation_alias="MIGRATIONS_AUTO_RUN")
    secret_encryption_key: str = Field(
        default="change-me-32-byte-base64-key",
        validation_alias="SECRET_ENCRYPTION_KEY",
    )
    agent_token_pepper: str = Field(
        default="change-me-agent-token-pepper",
        validation_alias=AliasChoices(
            "GRANTORA_AGENT_TOKEN_PEPPER",
            "AGENT_TOKEN_PEPPER",
            "TOKEN_HASH_PEPPER",
        ),
    )
    admin_bootstrap_token_hash: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GRANTORA_ADMIN_BOOTSTRAP_TOKEN_HASH",
            "ADMIN_BOOTSTRAP_TOKEN_HASH",
        ),
    )
    metrics_enabled: bool = Field(default=True, validation_alias="METRICS_ENABLED")
    request_id_header: str = Field(default="X-Request-Id", validation_alias="REQUEST_ID_HEADER")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
