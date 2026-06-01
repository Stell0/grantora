from __future__ import annotations

from urllib.parse import quote
from uuid import uuid4

import httpx
import pytest

from grantora.apisix import (
    DEFAULT_RUNTIME_ROUTE_ID,
    DEFAULT_RUNTIME_ROUTE_URIS,
    ApisixAdminClient,
    reconcile_apisix_routes,
)
from grantora.config import Settings
from grantora.db import Database
from grantora.secrets import SecretCipher

from .conftest import ApisixIntegrationTarget, IsolatedPostgresSchema

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_apisix_admin_api_can_create_update_and_read_route(
    apisix_target: ApisixIntegrationTarget,
) -> None:
    route_id = f"grantora-integration-{uuid4().hex}"
    route = {
        "name": "Grantora integration route",
        "uri": f"/grantora-integration/{route_id}",
        "upstream": {"type": "roundrobin", "nodes": {"127.0.0.1:1": 1}},
        "plugins": {"request-id": {}},
        "status": 1,
    }

    try:
        async with ApisixAdminClient(
            apisix_target.admin_url,
            apisix_target.admin_key,
            timeout_seconds=apisix_target.timeout_seconds,
        ) as client:
            assert await client.get_route(route_id) is None
            created = await client.put_route(route_id, route)
            updated = await client.put_route(
                route_id,
                {**route, "plugins": {**route["plugins"], "prometheus": {}}},
            )
            read_back = await client.get_route(route_id)
    finally:
        await delete_apisix_route(apisix_target, route_id)

    assert created["uri"] == route["uri"]
    assert updated["plugins"] == {"request-id": {}, "prometheus": {}}
    assert read_back == updated


@pytest.mark.asyncio
async def test_apisix_reconciliation_is_idempotent_against_admin_api(
    current_postgres_schema: IsolatedPostgresSchema,
    apisix_target: ApisixIntegrationTarget,
) -> None:
    settings = Settings(
        database_url=current_postgres_schema.database_url,
        environment="integration",
        secret_encryption_key=SecretCipher.generate_key(),
        apisix_admin_url=apisix_target.admin_url,
        apisix_admin_key=apisix_target.admin_key,
    )
    database = Database(settings)

    async with ApisixAdminClient(
        apisix_target.admin_url,
        apisix_target.admin_key,
        timeout_seconds=apisix_target.timeout_seconds,
    ) as client:
        with database.session_factory() as session:
            first_result = await reconcile_apisix_routes(session, settings, client)
        with database.session_factory() as session:
            second_result = await reconcile_apisix_routes(session, settings, client)
        route = await client.get_route(DEFAULT_RUNTIME_ROUTE_ID)

    assert first_result.status == "ok"
    assert first_result.checked_routes == 1
    assert second_result.status == "ok"
    assert second_result.checked_routes == 1
    assert second_result.changed_routes == 0
    assert route is not None
    assert route["uris"] == list(DEFAULT_RUNTIME_ROUTE_URIS)
    assert route["labels"] == {
        "grantora_managed": "true",
        "grantora_route_id": DEFAULT_RUNTIME_ROUTE_ID,
    }
    database.dispose()


async def delete_apisix_route(target: ApisixIntegrationTarget, route_id: str) -> None:
    async with httpx.AsyncClient(
        base_url=target.admin_url.rstrip("/"),
        headers={"X-API-KEY": target.admin_key},
        timeout=target.timeout_seconds,
    ) as client:
        await client.delete(f"/apisix/admin/routes/{quote(route_id, safe='')}")
