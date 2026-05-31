from __future__ import annotations

from pathlib import Path

from grantora.config import Settings

ROOT = Path(__file__).parents[2]


def test_compose_wires_apisix_sync_settings_and_local_admin_port() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "APISIX_SYNC_ENABLED: ${APISIX_SYNC_ENABLED:-true}" in compose
    assert "APISIX_SYNC_INTERVAL_SECONDS: ${APISIX_SYNC_INTERVAL_SECONDS:-30}" in compose
    assert "APISIX_FAIL_CLOSED: ${APISIX_FAIL_CLOSED:-true}" in compose
    assert "AUDIT_RETENTION_DAYS: ${AUDIT_RETENTION_DAYS:-365}" in compose
    assert "USAGE_RETENTION_DAYS: ${USAGE_RETENTION_DAYS:-365}" in compose
    assert "OTEL_TRACING_ENABLED: ${OTEL_TRACING_ENABLED:-false}" in compose
    assert "OTEL_SERVICE_NAME: ${OTEL_SERVICE_NAME:-grantora}" in compose
    assert '"127.0.0.1:${APISIX_ADMIN_PORT:-9180}:9180"' in compose


def test_apisix_admin_config_is_not_open_to_the_world() -> None:
    config = (ROOT / "containers" / "apisix" / "config.yaml").read_text(encoding="utf-8")

    assert "0.0.0.0/0" not in config
    assert "127.0.0.0/24" in config
    assert "10.0.0.0/8" in config
    assert "172.16.0.0/12" in config
    assert "192.168.0.0/16" in config


def test_apisix_environment_reference_is_wired_to_settings(monkeypatch) -> None:
    monkeypatch.setenv("APISIX_SYNC_ENABLED", "true")
    monkeypatch.setenv("APISIX_SYNC_INTERVAL_SECONDS", "42")
    monkeypatch.setenv("APISIX_FAIL_CLOSED", "false")
    monkeypatch.setenv("APISIX_ADMIN_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("APISIX_RUNTIME_UPSTREAM_NODE", "grantora-api:18080")
    monkeypatch.setenv("APISIX_RATE_LIMIT_COUNT", "250")
    monkeypatch.setenv("APISIX_RATE_LIMIT_TIME_WINDOW", "15")

    settings = Settings(_env_file=None)

    assert settings.apisix_sync_enabled is True
    assert settings.apisix_sync_interval_seconds == 42
    assert settings.apisix_fail_closed is False
    assert settings.apisix_admin_timeout_seconds == 7
    assert settings.apisix_runtime_upstream_node == "grantora-api:18080"
    assert settings.apisix_rate_limit_count == 250
    assert settings.apisix_rate_limit_time_window == 15


def test_observability_environment_reference_is_wired_to_settings(monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "30")
    monkeypatch.setenv("USAGE_RETENTION_DAYS", "90")
    monkeypatch.setenv("OTEL_TRACING_ENABLED", "true")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "grantora-ops")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318/v1/traces")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT_SECONDS", "12")

    settings = Settings(_env_file=None)

    assert settings.audit_retention_days == 30
    assert settings.usage_retention_days == 90
    assert settings.otel_tracing_enabled is True
    assert settings.otel_service_name == "grantora-ops"
    assert settings.otel_exporter_otlp_endpoint == "http://collector:4318/v1/traces"
    assert settings.otel_exporter_otlp_timeout_seconds == 12


def test_security_environment_reference_is_wired_to_settings(monkeypatch) -> None:
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "2048")
    monkeypatch.setenv("FEATURE_OIDC", "true")
    monkeypatch.setenv("OIDC_ADMIN_SUBJECTS", "alice@example.test,bob@example.test")
    monkeypatch.setenv("OIDC_SUBJECT_HEADER", "X-Forwarded-User")
    monkeypatch.setenv("FEATURE_EXTERNAL_SECRET_STORE", "true")

    settings = Settings(_env_file=None)

    assert settings.max_request_body_bytes == 2048
    assert settings.feature_oidc is True
    assert settings.oidc_admin_subjects == "alice@example.test,bob@example.test"
    assert settings.oidc_subject_header == "X-Forwarded-User"
    assert settings.feature_external_secret_store is True


def test_release_security_gates_are_defined() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")

    assert "security-scan:" in makefile
    assert "python -m pip_audit --strict --format json" in makefile
    assert "sbom:" in makefile
    assert "python -m cyclonedx_py environment --output-format JSON" in makefile
    assert "container-scan:" in makefile
    assert "trivy image --severity CRITICAL,HIGH --exit-code 1" in makefile
    assert "release-security: security-scan sbom container-scan" in makefile
    assert "pip-audit" in pyproject
    assert "cyclonedx-bom" in pyproject
    assert "actions/upload-artifact" in workflow
    assert "container-vulnerabilities.json" in workflow
    assert 'exit-code: "1"' in workflow
