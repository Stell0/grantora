from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from grantora.adapters.base import AdapterResult, HealthResult, InvocationContext, SecretMaterial
from grantora.db.models import ApplicationInstance, Capability

DEFAULT_PHONEBOOK_SEARCH_PATH = "/api/phonebook/search"
DEFAULT_PHONEBOOK_LIMIT = 50
NETHVOICE_SOURCE = "nethvoice"


class NethVoicePhonebookAdapter:
    id = "nethvoice"
    provider_type = "nethvoice"

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        phonebook_search_path: str = DEFAULT_PHONEBOOK_SEARCH_PATH,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._phonebook_search_path = phonebook_search_path

    async def invoke(
        self,
        capability: Capability,
        input_data: dict[str, Any],
        context: InvocationContext,
        secret: SecretMaterial,
    ) -> AdapterResult:
        if capability.operation != "phonebook.search":
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

        try:
            async with httpx.AsyncClient(
                base_url=context.application.base_url,
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    self._phonebook_search_path,
                    headers=auth_headers,
                    params={"query": query, "limit": limit},
                )
        except httpx.TimeoutException:
            return AdapterResult.error(
                "upstream_timeout",
                "The upstream application timed out",
                retryable=True,
            )
        except httpx.RequestError:
            return AdapterResult.error(
                "upstream_error",
                "The upstream application could not be reached",
                retryable=True,
            )

        error_result = _error_result_from_response(response)
        if error_result is not None:
            return error_result

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
        return HealthResult(status="ok")


def _auth_headers(secret: SecretMaterial) -> dict[str, str] | None:
    if secret.secret_type == "bearer_token":
        return {"Authorization": f"Bearer {secret.value}"}
    if secret.secret_type == "api_key":
        return {"X-API-Key": secret.value}
    return None


def _requested_limit(input_data: Mapping[str, Any], input_schema: Mapping[str, Any]) -> int:
    schema_limit = _schema_maximum_limit(input_schema)
    requested_limit = input_data.get("limit", schema_limit)
    if isinstance(requested_limit, bool) or not isinstance(requested_limit, int):
        return schema_limit
    return min(max(requested_limit, 1), schema_limit)


def _schema_maximum_limit(input_schema: Mapping[str, Any]) -> int:
    properties = input_schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return DEFAULT_PHONEBOOK_LIMIT
    limit_schema = properties.get("limit", {})
    if not isinstance(limit_schema, Mapping):
        return DEFAULT_PHONEBOOK_LIMIT
    maximum = limit_schema.get("maximum")
    if isinstance(maximum, bool) or not isinstance(maximum, int):
        return DEFAULT_PHONEBOOK_LIMIT
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
            "The upstream phonebook endpoint was not found",
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


def _normalized_contacts(payload: Any, limit: int) -> list[dict[str, str]] | None:
    raw_contacts = _extract_contact_items(payload)
    if raw_contacts is None:
        return None

    contacts = []
    for raw_contact in raw_contacts[:limit]:
        contact = _normalized_contact(raw_contact)
        if contact is None:
            return None
        contacts.append(contact)
    return contacts


def _extract_contact_items(payload: Any) -> list[Mapping[str, Any]] | None:
    raw_items: Any
    if isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, Mapping):
        raw_items = _first_present(payload, "contacts", "results", "items")
        if raw_items is None:
            data = payload.get("data")
            if isinstance(data, Mapping):
                raw_items = _first_present(data, "contacts", "results", "items")
            else:
                raw_items = data
    else:
        return None

    if not isinstance(raw_items, list):
        return None
    if not all(isinstance(item, Mapping) for item in raw_items):
        return None
    return raw_items


def _first_present(payload: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _normalized_contact(raw_contact: Mapping[str, Any]) -> dict[str, str] | None:
    display_name = _display_name(raw_contact)
    phone = _phone_number(raw_contact)
    if display_name is None or phone is None:
        return None
    return {
        "display_name": display_name,
        "phone": phone,
        "company": _first_string(
            raw_contact,
            "company",
            "company_name",
            "companyName",
            "organization",
            "organisation",
            "org",
        )
        or "",
        "source": NETHVOICE_SOURCE,
    }


def _display_name(raw_contact: Mapping[str, Any]) -> str | None:
    display_name = _first_string(
        raw_contact,
        "display_name",
        "displayName",
        "full_name",
        "fullName",
        "fullname",
        "name",
    )
    if display_name is not None:
        return display_name
    name_parts = [
        value
        for value in (
            _first_string(raw_contact, "first_name", "firstName", "given_name", "givenName"),
            _first_string(raw_contact, "last_name", "lastName", "family_name", "familyName"),
        )
        if value is not None
    ]
    if name_parts:
        return " ".join(name_parts)
    return None


def _phone_number(raw_contact: Mapping[str, Any]) -> str | None:
    phone = _first_string(
        raw_contact,
        "phone",
        "phone_number",
        "phoneNumber",
        "number",
        "mobile",
        "mobile_phone",
        "mobilePhone",
        "telephone",
        "extension",
    )
    if phone is not None:
        return phone

    for key in ("phones", "phone_numbers", "phoneNumbers", "numbers"):
        value = raw_contact.get(key)
        phone = _phone_from_sequence(value)
        if phone is not None:
            return phone
    return None


def _phone_from_sequence(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for phone_entry in value:
        if isinstance(phone_entry, str):
            phone = phone_entry.strip()
            if phone:
                return phone
        if isinstance(phone_entry, Mapping):
            phone = _first_string(phone_entry, "number", "phone", "value")
            if phone is not None:
                return phone
    return None


def _first_string(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            normalized_value = value.strip()
            if normalized_value:
                return normalized_value
    return None
