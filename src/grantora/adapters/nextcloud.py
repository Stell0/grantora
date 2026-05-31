from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from grantora.adapters.base import AdapterResult, HealthResult, InvocationContext, SecretMaterial
from grantora.adapters.http import RetryPolicy, send_with_read_only_retries
from grantora.db.models import ApplicationInstance, Capability

DEFAULT_FILES_SEARCH_PATH = "/ocs/v2.php/search/providers/files/search"
DEFAULT_FILES_LIMIT = 50
DEFAULT_MAX_RESPONSE_BYTES = 10_485_760
NEXTCLOUD_SOURCE = "nextcloud"


class NextcloudFilesAdapter:
    id = "nextcloud"
    provider_type = "nextcloud"

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        connect_timeout_seconds: float | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        verify: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        files_search_path: str = DEFAULT_FILES_SEARCH_PATH,
        health_check_path: str | None = DEFAULT_FILES_SEARCH_PATH,
        read_retry_attempts: int = 2,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._verify = verify
        self._transport = transport
        self._files_search_path = files_search_path
        self._health_check_path = health_check_path
        self._retry_policy = RetryPolicy(read_only_attempts=read_retry_attempts)

    async def invoke(
        self,
        capability: Capability,
        input_data: dict[str, Any],
        context: InvocationContext,
        secret: SecretMaterial,
    ) -> AdapterResult:
        if capability.operation != "files.search":
            return AdapterResult.error(
                "adapter_operation_unsupported",
                "Capability operation is not supported by this adapter",
            )
        if context.application.base_url is None:
            return AdapterResult.error(
                "upstream_not_found",
                "The upstream application endpoint was not configured",
            )

        auth_headers = _auth_headers(secret)
        if auth_headers is None:
            return AdapterResult.error(
                "secret_type_unsupported",
                "Required upstream secret could not be used",
            )

        limit = _requested_limit(input_data, capability.input_schema)
        query = str(input_data.get("query", "")).strip()

        async with httpx.AsyncClient(
            base_url=context.application.base_url,
            timeout=self._timeout_config(),
            verify=self._verify,
            transport=self._transport,
        ) as client:

            async def send() -> httpx.Response:
                return await client.get(
                    self._files_search_path,
                    headers={
                        **auth_headers,
                        "Accept": "application/json",
                        "OCS-APIRequest": "true",
                    },
                    params={"term": query, "limit": limit},
                )

            response, request_error = await send_with_read_only_retries(
                capability,
                send,
                self._retry_policy,
            )

        if request_error is not None:
            return request_error
        if response is None:
            return AdapterResult.error(
                "upstream_error",
                "The upstream application could not be reached",
                retryable=True,
            )

        error_result = _error_result_from_response(response)
        if error_result is not None:
            return error_result
        if _response_too_large(response, self._max_response_bytes):
            return AdapterResult.error(
                "upstream_payload_too_large",
                "The upstream application response was too large",
                upstream_status=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError:
            return _invalid_response(response.status_code)

        files = _normalized_files(payload, limit)
        if files is None:
            return _invalid_response(response.status_code)

        return AdapterResult.ok(
            {"files": files},
            upstream_status=response.status_code,
            safe_metadata={"provider_type": self.provider_type},
        )

    async def health(self, application: ApplicationInstance) -> HealthResult:
        if application.base_url is None:
            return HealthResult(
                status="error",
                safe_message="The upstream application endpoint was not configured",
            )
        if self._health_check_path is None:
            return HealthResult(status="ok")

        try:
            async with httpx.AsyncClient(
                base_url=application.base_url,
                timeout=self._timeout_config(),
                verify=self._verify,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    self._health_check_path,
                    headers={"Accept": "application/json", "OCS-APIRequest": "true"},
                    params={"term": "", "limit": 1},
                )
        except httpx.TimeoutException:
            return HealthResult(
                status="error",
                safe_message="The upstream application timed out",
            )
        except httpx.RequestError:
            return HealthResult(
                status="error",
                safe_message="The upstream application could not be reached",
            )

        if response.status_code < 400:
            return HealthResult(status="ok")
        if response.status_code in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN}:
            return HealthResult(
                status="ok",
                safe_message="The upstream application is reachable but requires credentials",
            )
        if response.status_code == httpx.codes.NOT_FOUND:
            return HealthResult(
                status="error",
                safe_message="The upstream file search endpoint was not found",
            )
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            return HealthResult(
                status="error",
                safe_message="The upstream application rate limit was reached",
            )
        return HealthResult(
            status="error",
            safe_message="The upstream application returned an error",
        )

    def _timeout_config(self) -> httpx.Timeout:
        if self._connect_timeout_seconds is None:
            return httpx.Timeout(self._timeout_seconds)
        return httpx.Timeout(self._timeout_seconds, connect=self._connect_timeout_seconds)


def _auth_headers(secret: SecretMaterial) -> dict[str, str] | None:
    if secret.secret_type == "bearer_token":
        return {"Authorization": f"Bearer {secret.value}"}
    if secret.secret_type != "basic_auth" or ":" not in secret.value:
        return None
    encoded = base64.b64encode(secret.value.encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _requested_limit(input_data: Mapping[str, Any], input_schema: Mapping[str, Any]) -> int:
    schema_limit = _schema_maximum_limit(input_schema)
    requested_limit = input_data.get("limit", schema_limit)
    if isinstance(requested_limit, bool) or not isinstance(requested_limit, int):
        return schema_limit
    return min(max(requested_limit, 1), schema_limit)


def _schema_maximum_limit(input_schema: Mapping[str, Any]) -> int:
    properties = input_schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return DEFAULT_FILES_LIMIT
    limit_schema = properties.get("limit", {})
    if not isinstance(limit_schema, Mapping):
        return DEFAULT_FILES_LIMIT
    maximum = limit_schema.get("maximum")
    if isinstance(maximum, bool) or not isinstance(maximum, int):
        return DEFAULT_FILES_LIMIT
    return max(maximum, 1)


def _error_result_from_response(response: httpx.Response) -> AdapterResult | None:
    upstream_status = response.status_code
    if upstream_status < 400:
        return None
    if upstream_status in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN}:
        return AdapterResult.error(
            "upstream_unauthorized",
            "The upstream application rejected the delegated credentials",
            upstream_status=upstream_status,
        )
    if upstream_status == httpx.codes.NOT_FOUND:
        return AdapterResult.error(
            "upstream_not_found",
            "The upstream file search endpoint was not found",
            upstream_status=upstream_status,
        )
    if upstream_status == httpx.codes.TOO_MANY_REQUESTS:
        return AdapterResult.error(
            "upstream_rate_limited",
            "The upstream application rate limit was reached",
            upstream_status=upstream_status,
            retryable=True,
        )
    if upstream_status >= 500:
        return AdapterResult.error(
            "upstream_error",
            "The upstream application returned an error",
            upstream_status=upstream_status,
            retryable=True,
        )
    return AdapterResult.error(
        "upstream_error",
        "The upstream application returned an error",
        upstream_status=upstream_status,
    )


def _invalid_response(upstream_status: int | None) -> AdapterResult:
    return AdapterResult.error(
        "upstream_invalid_response",
        "The upstream application returned an invalid response",
        upstream_status=upstream_status,
    )


def _response_too_large(response: httpx.Response, max_response_bytes: int) -> bool:
    return len(response.content) > max_response_bytes


def _normalized_files(payload: Any, limit: int) -> list[dict[str, Any]] | None:
    raw_files = _extract_file_items(payload)
    if raw_files is None:
        return None

    files = []
    for raw_file in raw_files[:limit]:
        file_item = _normalized_file(raw_file)
        if file_item is None:
            return None
        files.append(file_item)
    return files


def _extract_file_items(payload: Any) -> list[Mapping[str, Any]] | None:
    raw_items: Any
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, Mapping):
        raw_items = _items_from_ocs_payload(payload)
        if raw_items is None:
            raw_items = _first_present(payload, "files", "entries", "results", "items")
        if raw_items is None:
            data = payload.get("data")
            if isinstance(data, Mapping):
                raw_items = _first_present(data, "files", "entries", "results", "items")
            else:
                raw_items = data
    else:
        return None

    if not isinstance(raw_items, list):
        return None
    if not all(isinstance(item, Mapping) for item in raw_items):
        return None
    return raw_items


def _items_from_ocs_payload(payload: Mapping[str, Any]) -> Any:
    ocs = payload.get("ocs")
    if not isinstance(ocs, Mapping):
        return None
    data = ocs.get("data")
    if isinstance(data, Mapping):
        return _first_present(data, "entries", "files", "results", "items")
    return data


def _normalized_file(raw_file: Mapping[str, Any]) -> dict[str, Any] | None:
    path = _file_path(raw_file)
    display_name = _first_string(
        raw_file,
        "display_name",
        "displayName",
        "title",
        "name",
        "file_name",
        "fileName",
    )
    if display_name is None and path is not None:
        display_name = path.rstrip("/").rsplit("/", 1)[-1] or path
    if path is None or display_name is None:
        return None
    return {
        "path": path,
        "display_name": display_name,
        "mime_type": _file_string(raw_file, "mime_type", "mimeType", "mimetype", "content_type")
        or "",
        "size": _file_int(raw_file, "size", "bytes", "file_size", "fileSize"),
        "modified_at": _modified_at(raw_file),
        "source": NEXTCLOUD_SOURCE,
    }


def _file_path(raw_file: Mapping[str, Any]) -> str | None:
    path = _file_string(raw_file, "path", "file_path", "filePath", "dav_path", "davPath")
    if path is not None:
        return _normalize_path(path)
    resource_url = _file_string(raw_file, "resourceUrl", "resource_url", "url", "link", "href")
    if resource_url is None:
        return None
    return _normalize_path(resource_url)


def _normalize_path(value: str) -> str | None:
    parsed = urlparse(value)
    path = unquote(parsed.path if parsed.scheme else value)
    marker = "/remote.php/dav/files/"
    if marker in path:
        path = path.split(marker, 1)[1]
        path = path.split("/", 1)[1] if "/" in path else ""
    if not path.startswith("/"):
        path = f"/{path}"
    return path or "/"


def _modified_at(raw_file: Mapping[str, Any]) -> str | None:
    value = _file_value(raw_file, "modified_at", "modifiedAt", "last_modified", "mtime")
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        value = value.strip()
        if value:
            return value
    return None


def _file_string(raw_file: Mapping[str, Any], *keys: str) -> str | None:
    value = _file_value(raw_file, *keys)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _file_int(raw_file: Mapping[str, Any], *keys: str) -> int | None:
    value = _file_value(raw_file, *keys)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _file_value(raw_file: Mapping[str, Any], *keys: str) -> Any:
    value = _first_present(raw_file, *keys)
    if value is not None:
        return value
    attributes = raw_file.get("attributes")
    if isinstance(attributes, Mapping):
        return _first_present(attributes, *keys)
    return None


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _first_string(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized_value = value.strip()
            if normalized_value:
                return normalized_value
    return None
