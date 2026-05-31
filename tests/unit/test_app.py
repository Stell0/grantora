import json
import logging

from fastapi.testclient import TestClient

from grantora.config import Settings
from grantora.logging import JsonLogFormatter
from grantora.main import create_app


class Probe:
    def ping(self) -> None:
        return None

    def dispose(self) -> None:
        return None


def test_create_app_imports_without_connecting_to_database() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")

    app = create_app(settings=settings, database=Probe())

    assert app.title == "Grantora Gateway API"


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
