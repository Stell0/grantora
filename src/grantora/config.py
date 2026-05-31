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
    apisix_admin_url: str = Field(default="http://apisix:9180", validation_alias="APISIX_ADMIN_URL")
    apisix_admin_key: str = Field(default="change-me", validation_alias="APISIX_ADMIN_KEY")
    apisix_admin_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        validation_alias="APISIX_ADMIN_TIMEOUT_SECONDS",
    )
    apisix_sync_enabled: bool = Field(default=False, validation_alias="APISIX_SYNC_ENABLED")
    apisix_sync_interval_seconds: int = Field(
        default=30,
        gt=0,
        validation_alias="APISIX_SYNC_INTERVAL_SECONDS",
    )
    apisix_fail_closed: bool = Field(default=True, validation_alias="APISIX_FAIL_CLOSED")
    apisix_runtime_upstream_node: str = Field(
        default="grantora-api:8080",
        validation_alias="APISIX_RUNTIME_UPSTREAM_NODE",
    )
    apisix_rate_limit_count: int = Field(
        default=1000,
        gt=0,
        validation_alias="APISIX_RATE_LIMIT_COUNT",
    )
    apisix_rate_limit_time_window: int = Field(
        default=60,
        gt=0,
        validation_alias="APISIX_RATE_LIMIT_TIME_WINDOW",
    )
    metrics_enabled: bool = Field(default=True, validation_alias="METRICS_ENABLED")
    audit_retention_days: int = Field(default=365, gt=0, validation_alias="AUDIT_RETENTION_DAYS")
    usage_retention_days: int = Field(default=365, gt=0, validation_alias="USAGE_RETENTION_DAYS")
    otel_tracing_enabled: bool = Field(default=False, validation_alias="OTEL_TRACING_ENABLED")
    otel_service_name: str = Field(default="grantora", validation_alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    otel_exporter_otlp_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        validation_alias="OTEL_EXPORTER_OTLP_TIMEOUT_SECONDS",
    )
    request_id_header: str = Field(default="X-Request-Id", validation_alias="REQUEST_ID_HEADER")
    default_request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias="DEFAULT_REQUEST_TIMEOUT_SECONDS",
    )
    upstream_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias="UPSTREAM_TIMEOUT_SECONDS",
    )
    upstream_connect_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        validation_alias="UPSTREAM_CONNECT_TIMEOUT_SECONDS",
    )
    upstream_tls_verify: bool = Field(default=True, validation_alias="UPSTREAM_TLS_VERIFY")
    upstream_max_response_bytes: int = Field(
        default=10_485_760,
        gt=0,
        validation_alias="UPSTREAM_MAX_RESPONSE_BYTES",
    )
    upstream_read_retry_attempts: int = Field(
        default=2,
        gt=0,
        validation_alias="UPSTREAM_READ_RETRY_ATTEMPTS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
