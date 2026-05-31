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

    async def put_route(self, route_id: str, route: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("PUT", self._route_path(route_id), json=route)
        return self._route_from_response(response)

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
                "APISIX Admin API returned an invalid route response",
                response.status_code,
            )

        value = payload.get("value")
        if isinstance(value, dict):
            return value
        return payload

    @staticmethod
    def _route_path(route_id: str) -> str:
        return f"/apisix/admin/routes/{quote(route_id, safe='')}"
