import json
import logging
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from grantora.config import Settings
from grantora.db import Base, Database
from grantora.db.models import ApisixSyncStatus
from grantora.logging import JsonLogFormatter
from grantora.main import create_app


class Probe:
    def ping(self) -> None:
        return None

    def dispose(self) -> None:
        return None


class RecordingApisixClient:
    def __init__(self) -> None:
        self.routes: dict[str, dict[str, Any]] = {}
        self.puts: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "RecordingApisixClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def get_route(self, route_id: str) -> dict[str, Any] | None:
        return self.routes.get(route_id)

    async def put_route(self, route_id: str, route: dict[str, Any]) -> dict[str, Any]:
        self.puts.append((route_id, route))
        self.routes[route_id] = route
        return route


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
