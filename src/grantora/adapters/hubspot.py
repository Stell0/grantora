from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from grantora.adapters.base import AdapterResult, HealthResult, InvocationContext, SecretMaterial
from grantora.adapters.http import RetryPolicy, send_with_read_only_retries
from grantora.db.models import ApplicationInstance, Capability

DEFAULT_CONTACTS_SEARCH_PATH = "/crm/v3/objects/contacts/search"
DEFAULT_CONTACTS_HEALTH_PATH = "/crm/v3/objects/contacts"
DEFAULT_CONTACTS_LIMIT = 50
DEFAULT_MAX_RESPONSE_BYTES = 10_485_760
HUBSPOT_SOURCE = "hubspot"
HUBSPOT_CONTACT_PROPERTIES = (
    "email",
    "firstname",
    "lastname",
    "company",
    "phone",
    "jobtitle",
)


class HubSpotContactsAdapter:
    id = "hubspot"
    provider_type = "hubspot"

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        connect_timeout_seconds: float | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        verify: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        contacts_search_path: str = DEFAULT_CONTACTS_SEARCH_PATH,
        health_check_path: str | None = DEFAULT_CONTACTS_HEALTH_PATH,
        read_retry_attempts: int = 2,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._connect_timeout_seconds = connect_timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._verify = verify
        self._transport = transport
        self._contacts_search_path = contacts_search_path
        self._health_check_path = health_check_path
        self._retry_policy = RetryPolicy(read_only_attempts=read_retry_attempts)

    async def invoke(
        self,
        capability: Capability,
        input_data: dict[str, Any],
        context: InvocationContext,
        secret: SecretMaterial,
    ) -> AdapterResult:
        if capability.operation != "contacts.search":
            return AdapterResult.error(
                "adapter_operation_unsupported",
                "Capability operation is not supported by this adapter",
            )
        if context.application.base_url is None:
            return AdapterResult.error(
                "upstream_not_found",
                "The upstream application endpoint was not configured",
            )
        if secret.secret_type != "bearer_token":
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
                return await client.post(
                    self._contacts_search_path,
                    headers={
                        "Authorization": f"Bearer {secret.value}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "limit": limit,
                        "properties": list(HUBSPOT_CONTACT_PROPERTIES),
                    },
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

        contacts = _normalized_contacts(payload, limit)
        if contacts is None:
            return _invalid_response(response.status_code)

        return AdapterResult.ok(
            {"contacts": contacts},
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
                    headers={"Accept": "application/json"},
                    params={"limit": 1, "properties": "email"},
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
                safe_message="The upstream HubSpot contacts endpoint was not found",
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


def _requested_limit(input_data: Mapping[str, Any], input_schema: Mapping[str, Any]) -> int:
    schema_limit = _schema_maximum_limit(input_schema)
    requested_limit = input_data.get("limit", schema_limit)
    if isinstance(requested_limit, bool) or not isinstance(requested_limit, int):
        return schema_limit
    return min(max(requested_limit, 1), schema_limit)


def _schema_maximum_limit(input_schema: Mapping[str, Any]) -> int:
    properties = input_schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return DEFAULT_CONTACTS_LIMIT
    limit_schema = properties.get("limit", {})
    if not isinstance(limit_schema, Mapping):
        return DEFAULT_CONTACTS_LIMIT
    maximum = limit_schema.get("maximum")
    if isinstance(maximum, bool) or not isinstance(maximum, int):
        return DEFAULT_CONTACTS_LIMIT
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
            "The upstream HubSpot contacts endpoint was not found",
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


def _normalized_contacts(payload: Any, limit: int) -> list[dict[str, Any]] | None:
    if not isinstance(payload, Mapping):
        return None
    raw_contacts = payload.get("results")
    if not isinstance(raw_contacts, list):
        return None

    contacts = []
    for raw_contact in raw_contacts[:limit]:
        if not isinstance(raw_contact, Mapping):
            return None
        contact = _normalized_contact(raw_contact)
        if contact is None:
            return None
        contacts.append(contact)
    return contacts


def _normalized_contact(raw_contact: Mapping[str, Any]) -> dict[str, Any] | None:
    properties = raw_contact.get("properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, Mapping):
        return None

    contact_id = _first_string(raw_contact, "id") or _first_string(properties, "hs_object_id")
    if contact_id is None:
        return None

    display_name = (
        _display_name(properties)
        or _first_string(properties, "email", "company")
        or contact_id
    )
    return {
        "id": contact_id,
        "display_name": display_name,
        "email": _first_string(properties, "email"),
        "company": _first_string(properties, "company"),
        "phone": _first_string(properties, "phone"),
        "job_title": _first_string(properties, "jobtitle", "job_title"),
        "source": HUBSPOT_SOURCE,
    }


def _display_name(properties: Mapping[str, Any]) -> str | None:
    display_name = _first_string(properties, "display_name", "displayName", "name")
    if display_name is not None:
        return display_name
    name_parts = [
        value
        for value in (
            _first_string(properties, "firstname", "first_name", "firstName"),
            _first_string(properties, "lastname", "last_name", "lastName"),
        )
        if value is not None
    ]
    if name_parts:
        return " ".join(name_parts)
    return None


def _first_string(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized_value = value.strip()
            if normalized_value:
                return normalized_value
    return None
