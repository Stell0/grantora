import json
import logging
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client.parser import text_string_to_metric_families

from grantora.config import Settings
from grantora.db import Base, Database
from grantora.db.models import ApisixSyncStatus, Workspace
from grantora.logging import JsonLogFormatter
from grantora.main import create_app
from grantora.metrics import render_metrics
from grantora.tracing import create_trace_manager


class Probe:
    def ping(self) -> None:
        return None

    def dispose(self) -> None:
        return None


class RecordingApisixClient:
    def __init__(self) -> None:
        self.routes: dict[str, dict[str, Any]] = {}
        self.puts: list[tuple[str, dict[str, Any]]] = []
        self.deletes: list[str] = []

    async def __aenter__(self) -> "RecordingApisixClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def get_route(self, route_id: str) -> dict[str, Any] | None:
        return self.routes.get(route_id)

    async def list_routes(self) -> dict[str, dict[str, Any]]:
        return self.routes.copy()

    async def put_route(self, route_id: str, route: dict[str, Any]) -> dict[str, Any]:
        self.puts.append((route_id, route))
        self.routes[route_id] = route
        return route

    async def delete_route(self, route_id: str) -> bool:
        self.deletes.append(route_id)
        return self.routes.pop(route_id, None) is not None


def test_create_app_imports_without_connecting_to_database() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")

    app = create_app(settings=settings, database=Probe())

    assert app.title == "Grantora Gateway API"


def test_startup_apisix_sync_disabled_never_writes(tmp_path: Path) -> None:
    settings = make_database_settings(tmp_path, apisix_sync_enabled=False)
    database = create_database(settings)
    app = create_app(settings=settings, database=database)
    apisix_client = RecordingApisixClient()
    app.state.apisix_client_factory = lambda _settings: apisix_client

    with TestClient(app):
        pass

    with database.session_factory() as session:
        sync_status = session.get(ApisixSyncStatus, "default")

    assert apisix_client.puts == []
    assert sync_status is None


def test_startup_creates_current_schema_from_metadata(tmp_path: Path) -> None:
    settings = make_database_settings(tmp_path)
    database = Database(settings)
    app = create_app(settings=settings, database=database)

    with TestClient(app):
        pass

    with database.session_factory() as session:
        workspace = Workspace(slug="startup-schema", display_name="Startup Schema")
        session.add(workspace)
        session.commit()

    database.dispose()


def test_startup_apisix_sync_enabled_reconciles_once(tmp_path: Path) -> None:
    settings = make_database_settings(
        tmp_path,
        apisix_sync_enabled=True,
        apisix_sync_interval_seconds=3600,
    )
    database = create_database(settings)
    app = create_app(settings=settings, database=database)
    apisix_client = RecordingApisixClient()
    app.state.apisix_client_factory = lambda _settings: apisix_client

    with TestClient(app):
        pass

    with database.session_factory() as session:
        sync_status = session.get(ApisixSyncStatus, "default")

    assert len(apisix_client.puts) == 1
    assert sync_status is not None
    assert sync_status.status == "ok"


def test_metrics_endpoint_exposes_observability_counters() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")
    app = create_app(settings=settings, database=Probe())

    with TestClient(app) as client:
        client.get("/healthz", headers={"X-Request-Id": "req_metrics"})
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "grantora_requests_total" in response.text
    assert "grantora_authorization_denied_total" in response.text
    assert "grantora_upstream_requests_total" in response.text
    assert "grantora_secret_resolution_total" in response.text
    assert "grantora_apisix_sync_total" in response.text


def test_request_body_limit_rejects_oversized_admin_request_before_handler() -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        environment="test",
        max_request_body_bytes=16,
    )
    app = create_app(settings=settings, database=Probe())

    with TestClient(app) as client:
        response = client.post(
            "/v1/admin/workspaces",
            headers={"Authorization": "Bearer secret-admin", "X-Request-Id": "req_too_big"},
            json={"slug": "a" * 32, "display_name": "too large"},
        )

    assert response.status_code == 413
    assert response.headers["X-Request-Id"] == "req_too_big"
    assert response.json() == {
        "request_id": "req_too_big",
        "status": "error",
        "error": {"code": "request_body_too_large", "message": "Request body is too large"},
    }


def test_request_body_limit_rejects_oversized_runtime_request_before_auth() -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        environment="test",
        max_request_body_bytes=16,
    )
    app = create_app(settings=settings, database=Probe())

    with TestClient(app) as client:
        response = client.post(
            "/v1/invoke/mock.echo",
            headers={"Authorization": "Bearer secret-agent", "X-Request-Id": "req_runtime_big"},
            json={"user": "alice", "input": {"query": "x" * 64}},
        )

    assert response.status_code == 413
    assert response.headers["X-Request-Id"] == "req_runtime_big"
    assert response.json()["error"]["code"] == "request_body_too_large"


def test_metrics_capture_auth_failure_and_apisix_sync_without_sensitive_data(
    tmp_path: Path,
) -> None:
    settings = make_database_settings(
        tmp_path,
        apisix_sync_enabled=True,
        apisix_sync_interval_seconds=3600,
    )
    database = create_database(settings)
    app = create_app(settings=settings, database=database)
    apisix_client = RecordingApisixClient()
    app.state.apisix_client_factory = lambda _settings: apisix_client
    auth_labels = {
        "workspace": "unknown",
        "agent": "unknown",
        "user": "unknown",
        "capability": "unknown",
        "status": "401",
    }
    sync_labels = {"status": "ok"}
    before_metrics = current_metrics()

    with TestClient(app) as client:
        response = client.get(
            "/v1/me",
            headers={"Authorization": "Bearer wrong-token", "X-Request-Id": "req_auth_fail"},
        )
        after_metrics = client.get("/metrics")

    assert response.status_code == 401
    assert metric_value(after_metrics.text, "grantora_requests_total", auth_labels) == (
        metric_value(before_metrics, "grantora_requests_total", auth_labels) + 1
    )
    assert metric_value(after_metrics.text, "grantora_apisix_sync_total", sync_labels) == (
        metric_value(before_metrics, "grantora_apisix_sync_total", sync_labels) + 1
    )
    assert "wrong-token" not in after_metrics.text
    assert "Authorization" not in after_metrics.text


def test_tracing_records_safe_request_span_and_response_traceparent() -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        environment="test",
        otel_tracing_enabled=True,
        otel_service_name="grantora-test",
    )
    exporter = InMemorySpanExporter()
    trace_manager = create_trace_manager(settings, exporter=exporter, use_simple_processor=True)
    app = create_app(settings=settings, database=Probe(), trace_manager=trace_manager)

    with TestClient(app) as client:
        response = client.get(
            "/healthz",
            headers={
                "Authorization": "Bearer secret-token",
                "X-Request-Id": "req_trace",
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            },
        )

    assert response.status_code == 200
    assert response.headers["traceparent"].startswith("00-")
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    attributes = dict(span.attributes)
    encoded_attributes = json.dumps(attributes, sort_keys=True)
    assert span.name == "http.request"
    assert span.resource.attributes["service.name"] == "grantora-test"
    assert attributes["http.request.method"] == "GET"
    assert attributes["http.response.status_code"] == 200
    assert attributes["grantora.request_id"] == "req_trace"
    assert attributes["url.path"] == "/healthz"
    assert "secret-token" not in encoded_attributes
    assert "Authorization" not in encoded_attributes


def test_request_logs_are_json_with_request_id_and_no_authorization_header(caplog) -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")
    app = create_app(settings=settings, database=Probe())

    with caplog.at_level(logging.INFO, logger="grantora.http"):
        with TestClient(app) as client:
            response = client.get(
                "/healthz",
                headers={"Authorization": "Bearer secret-token", "X-Request-Id": "req_logs"},
            )

    assert response.status_code == 200
    request_log = next(record for record in caplog.records if record.name == "grantora.http")
    payload = json.loads(JsonLogFormatter().format(request_log))
    encoded_payload = json.dumps(payload)
    assert payload["request_id"] == "req_logs"
    assert payload["status_code"] == 200
    assert "Authorization" not in encoded_payload
    assert "secret-token" not in encoded_payload


def make_database_settings(tmp_path: Path, **overrides: object) -> Settings:
    values = {
        "database_url": f"sqlite+pysqlite:///{tmp_path / 'grantora.sqlite'}",
        "environment": "test",
        **overrides,
    }
    return Settings(**values)


def create_database(settings: Settings) -> Database:
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    return database


def current_metrics() -> str:
    content, _media_type = render_metrics()
    return content.decode("utf-8")


def metric_value(metrics_text: str, metric_name: str, labels: dict[str, str]) -> float:
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            if sample.name == metric_name and sample.labels == labels:
                return float(sample.value)
    return 0.0
