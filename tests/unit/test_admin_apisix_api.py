from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from grantora.apisix import ApisixAdminAPIError
from grantora.auth import hash_token
from grantora.config import Settings
from grantora.db import Base, Database
from grantora.main import create_app


@dataclass(frozen=True)
class APIContext:
    client: TestClient
    database: Database
    settings: Settings
    apisix_client: InMemoryApisixClient


class InMemoryApisixClient:
    def __init__(self) -> None:
        self.routes: dict[str, dict[str, Any]] = {}
        self.puts: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> InMemoryApisixClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def get_route(self, route_id: str) -> dict[str, Any] | None:
        return self.routes.get(route_id)

    async def put_route(self, route_id: str, route: dict[str, Any]) -> dict[str, Any]:
        self.puts.append((route_id, route))
        self.routes[route_id] = route
        return route


class FailingApisixClient(InMemoryApisixClient):
    async def get_route(self, route_id: str) -> dict[str, Any] | None:
        raise ApisixAdminAPIError(
            "apisix_admin_unavailable",
            "APISIX Admin API is unavailable",
        )


@pytest.fixture()
def api_context(tmp_path: Path) -> Iterator[APIContext]:
    settings = make_test_settings(tmp_path)
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    app = create_app(settings=settings, database=database)
    apisix_client = InMemoryApisixClient()
    app.state.apisix_client_factory = lambda _settings: apisix_client

    with TestClient(app) as client:
        yield APIContext(
            client=client,
            database=database,
            settings=settings,
            apisix_client=apisix_client,
        )


def test_admin_apisix_sync_is_idempotent_and_status_is_reported(
    api_context: APIContext,
) -> None:
    initial_status_response = api_context.client.get(
        "/v1/admin/apisix/status",
        headers=authorization_headers("admin-token"),
    )
    first_sync_response = api_context.client.post(
        "/v1/admin/apisix/sync",
        headers={**authorization_headers("admin-token"), "X-Request-Id": "req_apisix_sync"},
    )
    second_sync_response = api_context.client.post(
        "/v1/admin/apisix/sync",
        headers=authorization_headers("admin-token"),
    )
    final_status_response = api_context.client.get(
        "/v1/admin/apisix/status",
        headers=authorization_headers("admin-token"),
    )

    assert initial_status_response.status_code == 200
    assert initial_status_response.json() == {
        "status": "never_run",
        "last_started_at": None,
        "last_finished_at": None,
        "checked_routes": 0,
        "changed_routes": 0,
        "error": None,
    }
    assert first_sync_response.status_code == 200
    assert first_sync_response.json() == {
        "request_id": "req_apisix_sync",
        "status": "ok",
        "last_started_at": None,
        "last_finished_at": None,
        "checked_routes": 1,
        "changed_routes": 1,
        "error": None,
    }
    assert second_sync_response.status_code == 200
    assert second_sync_response.json()["changed_routes"] == 0
    assert final_status_response.status_code == 200
    assert final_status_response.json()["status"] == "ok"
    assert final_status_response.json()["changed_routes"] == 0
    assert len(api_context.apisix_client.puts) == 1
    assert api_context.apisix_client.routes["gateway-runtime"]["plugins"] == {
        "prometheus": {},
        "request-id": {},
        "limit-count": {"count": 1000, "time_window": 60, "rejected_code": 429},
    }


def test_admin_apisix_sync_failure_reports_safe_status(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    app = create_app(settings=settings, database=database)
    app.state.apisix_client_factory = lambda _settings: FailingApisixClient()

    with TestClient(app) as client:
        sync_response = client.post(
            "/v1/admin/apisix/sync",
            headers=authorization_headers("admin-token"),
        )
        status_response = client.get(
            "/v1/admin/apisix/status",
            headers=authorization_headers("admin-token"),
        )

    assert sync_response.status_code == 200
    assert sync_response.json()["status"] == "error"
    assert sync_response.json()["error"] == {
        "code": "apisix_admin_unavailable",
        "message": "APISIX Admin API is unavailable",
    }
    assert status_response.status_code == 200
    assert status_response.json()["error"] == {
        "code": "apisix_admin_unavailable",
        "message": "APISIX Admin API is unavailable",
    }
    assert settings.apisix_admin_url not in sync_response.text
    assert settings.apisix_admin_key not in sync_response.text


def make_test_settings(tmp_path: Path) -> Settings:
    pepper = "test-token-pepper"
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'grantora.sqlite'}",
        environment="test",
        agent_token_pepper=pepper,
        admin_bootstrap_token_hash=hash_token("admin-token", pepper),
    )


def authorization_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
