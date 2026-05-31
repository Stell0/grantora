from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from grantora.apisix import ApisixAdminClient


@pytest.mark.asyncio
async def test_apisix_admin_client_can_create_update_and_read_route() -> None:
    routes: dict[str, dict[str, Any]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "admin-secret"
        route_id = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            route = routes.get(route_id)
            if route is None:
                return httpx.Response(404, json={"error_msg": "missing"})
            return httpx.Response(200, json={"value": route})
        if request.method == "PUT":
            route = json.loads(request.content.decode())
            routes[route_id] = route
            return httpx.Response(200, json={"value": route})
        return httpx.Response(405)

    transport = httpx.MockTransport(handler)
    route = {
        "uri": "/v1/*",
        "upstream": {"type": "roundrobin", "nodes": {"grantora-api:8080": 1}},
        "plugins": {"prometheus": {}, "request-id": {}},
    }

    async with ApisixAdminClient(
        "http://apisix.example.test",
        "admin-secret",
        transport=transport,
    ) as client:
        assert await client.get_route("gateway-runtime") is None

        created = await client.put_route("gateway-runtime", route)
        updated = await client.put_route(
            "gateway-runtime",
            {**route, "plugins": {**route["plugins"], "limit-count": {"count": 1000}}},
        )
        read_back = await client.get_route("gateway-runtime")

    assert created["uri"] == "/v1/*"
    assert updated["plugins"]["limit-count"] == {"count": 1000}
    assert read_back == updated
