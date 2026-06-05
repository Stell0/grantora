from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from grantora.apisix import (
    DEFAULT_RUNTIME_ROUTE_URIS,
    ApisixAdminAPIError,
    reconcile_apisix_routes,
)
from grantora.config import Settings
from grantora.db.models import ApisixRoute, ApisixSyncStatus, Base


class RecordingApisixClient:
    def __init__(self) -> None:
        self.routes: dict[str, dict[str, Any]] = {}
        self.puts: list[tuple[str, dict[str, Any]]] = []
        self.deletes: list[str] = []

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


class FailingReadApisixClient(RecordingApisixClient):
    async def get_route(self, route_id: str) -> dict[str, Any] | None:
        raise ApisixAdminAPIError(
            "apisix_admin_unavailable",
            "APISIX Admin API is unavailable",
        )


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_factory() as database_session:
        yield database_session

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_seeds_baseline_route_and_is_idempotent(session: Session) -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")
    client = RecordingApisixClient()

    first_result = await reconcile_apisix_routes(session, settings, client)
    second_result = await reconcile_apisix_routes(session, settings, client)

    route = session.get(ApisixRoute, "gateway-runtime")
    sync_status = session.get(ApisixSyncStatus, "default")

    assert first_result.status == "ok"
    assert first_result.checked_routes == 1
    assert first_result.changed_routes == 1
    assert second_result.status == "ok"
    assert second_result.changed_routes == 0
    assert len(client.puts) == 1
    assert route is not None
    assert route.plugins == {
        "prometheus": {},
        "request-id": {},
        "limit-count": {"count": 1000, "time_window": 60, "rejected_code": 429},
    }
    assert client.routes["gateway-runtime"] == {
        "name": "Grantora runtime API",
        "uris": list(DEFAULT_RUNTIME_ROUTE_URIS),
        "upstream": {"type": "roundrobin", "nodes": {"grantora-api:8080": 1}},
        "plugins": route.plugins,
        "labels": {
            "grantora_managed": "true",
            "grantora_route_id": "gateway-runtime",
        },
        "status": 1,
    }
    assert "/v1/admin" not in client.routes["gateway-runtime"]["uris"]
    assert "/v1/*" not in client.routes["gateway-runtime"]["uris"]
    assert "uri" not in client.routes["gateway-runtime"]
    assert sync_status is not None
    assert sync_status.status == "ok"
    assert sync_status.checked_routes == 1
    assert sync_status.changed_routes == 0


@pytest.mark.asyncio
async def test_fail_closed_preflight_failure_preserves_existing_route(session: Session) -> None:
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        environment="test",
        apisix_fail_closed=True,
    )
    existing_route = {
        "name": "Grantora runtime API",
        "uris": list(DEFAULT_RUNTIME_ROUTE_URIS),
        "upstream": {"type": "roundrobin", "nodes": {"grantora-api:8080": 1}},
        "plugins": {
            "prometheus": {},
            "request-id": {},
            "limit-count": {"count": 1000, "time_window": 60, "rejected_code": 429},
        },
        "labels": {
            "grantora_managed": "true",
            "grantora_route_id": "gateway-runtime",
        },
        "status": 1,
    }
    client = FailingReadApisixClient()
    client.routes["gateway-runtime"] = existing_route.copy()

    result = await reconcile_apisix_routes(session, settings, client)

    assert result.status == "error"
    assert result.error_code == "apisix_admin_unavailable"
    assert client.puts == []
    assert client.routes["gateway-runtime"] == existing_route


@pytest.mark.asyncio
async def test_reconcile_deletes_stale_managed_routes_but_preserves_foreign_routes(
    session: Session,
) -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")
    client = RecordingApisixClient()
    client.routes["grantora-stale"] = {
        "name": "Old Grantora route",
        "uri": "/old/*",
        "upstream": {"type": "roundrobin", "nodes": {"grantora-api:8080": 1}},
        "plugins": {"request-id": {}},
        "labels": {"grantora_managed": "true", "grantora_route_id": "grantora-stale"},
        "status": 1,
    }
    client.routes["foreign-route"] = {
        "name": "Foreign route",
        "uri": "/foreign/*",
        "upstream": {"type": "roundrobin", "nodes": {"foreign:8080": 1}},
        "plugins": {"request-id": {}},
        "status": 1,
    }

    result = await reconcile_apisix_routes(session, settings, client)

    assert result.status == "ok"
    assert result.changed_routes == 2
    assert client.deletes == ["grantora-stale"]
    assert "grantora-stale" not in client.routes
    assert "foreign-route" in client.routes


@pytest.mark.asyncio
async def test_reconcile_backfills_missing_apisix_tables(session: Session) -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", environment="test")
    client = RecordingApisixClient()

    ApisixSyncStatus.__table__.drop(session.bind)
    ApisixRoute.__table__.drop(session.bind)

    inspector = inspect(session.bind)
    assert ApisixRoute.__tablename__ not in inspector.get_table_names()
    assert ApisixSyncStatus.__tablename__ not in inspector.get_table_names()

    result = await reconcile_apisix_routes(session, settings, client)

    inspector = inspect(session.bind)
    assert result.status == "ok"
    assert ApisixRoute.__tablename__ in inspector.get_table_names()
    assert ApisixSyncStatus.__tablename__ in inspector.get_table_names()
    assert session.get(ApisixRoute, "gateway-runtime") is not None
    assert session.get(ApisixSyncStatus, "default") is not None
