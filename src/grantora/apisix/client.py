from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class ApisixAdminAPIError(Exception):
    def __init__(self, code: str, safe_message: str, status_code: int | None = None) -> None:
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


class ApisixAdminClient:
    def __init__(
        self,
        base_url: str,
        admin_key: str,
        *,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-KEY": admin_key},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> ApisixAdminClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_route(self, route_id: str) -> dict[str, Any] | None:
        response = await self._request("GET", self._route_path(route_id))
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        return self._route_from_response(response)

    async def list_routes(self) -> dict[str, dict[str, Any]]:
        response = await self._request("GET", "/apisix/admin/routes")
        return self._routes_from_response(response)

    async def put_route(self, route_id: str, route: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("PUT", self._route_path(route_id), json=route)
        return self._route_from_response(response)

    async def delete_route(self, route_id: str) -> bool:
        response = await self._request("DELETE", self._route_path(route_id))
        return response.status_code != httpx.codes.NOT_FOUND

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ApisixAdminAPIError(
                "apisix_admin_timeout",
                "APISIX Admin API did not respond before the timeout",
            ) from exc
        except httpx.RequestError as exc:
            raise ApisixAdminAPIError(
                "apisix_admin_unavailable",
                "APISIX Admin API is unavailable",
            ) from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            return response
        if response.status_code in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN}:
            raise ApisixAdminAPIError(
                "apisix_admin_unauthorized",
                "APISIX Admin API rejected the configured credentials",
                response.status_code,
            )
        if response.is_error:
            raise ApisixAdminAPIError(
                "apisix_admin_error",
                "APISIX Admin API returned an error",
                response.status_code,
            )
        return response

    def _route_from_response(self, response: httpx.Response) -> dict[str, Any]:
        payload = self._json_object(response, "route response")

        value = payload.get("value")
        if isinstance(value, dict):
            return value
        return payload

    def _routes_from_response(self, response: httpx.Response) -> dict[str, dict[str, Any]]:
        payload = self._json_object(response, "route list response")
        route_items = payload.get("list")
        if not isinstance(route_items, list):
            raise ApisixAdminAPIError(
                "apisix_admin_invalid_response",
                "APISIX Admin API returned an invalid route list response",
                response.status_code,
            )

        routes: dict[str, dict[str, Any]] = {}
        for item in route_items:
            route_id, route = self._route_from_list_item(item)
            if route_id is not None and route is not None:
                routes[route_id] = route
        return routes

    def _json_object(self, response: httpx.Response, response_name: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApisixAdminAPIError(
                "apisix_admin_invalid_response",
                "APISIX Admin API returned invalid JSON",
                response.status_code,
            ) from exc

        if not isinstance(payload, dict):
            raise ApisixAdminAPIError(
                "apisix_admin_invalid_response",
                f"APISIX Admin API returned an invalid {response_name}",
                response.status_code,
            )
        return payload

    @staticmethod
    def _route_from_list_item(item: object) -> tuple[str | None, dict[str, Any] | None]:
        if not isinstance(item, dict):
            return None, None

        value = item.get("value")
        route = value if isinstance(value, dict) else item
        route_id = route.get("id")
        if not isinstance(route_id, str):
            route_id = ApisixAdminClient._route_id_from_key(item.get("key"))
        return route_id, route

    @staticmethod
    def _route_id_from_key(key: object) -> str | None:
        if not isinstance(key, str) or not key:
            return None
        return key.rstrip("/").rsplit("/", 1)[-1] or None

    @staticmethod
    def _route_path(route_id: str) -> str:
        return f"/apisix/admin/routes/{quote(route_id, safe='')}"
