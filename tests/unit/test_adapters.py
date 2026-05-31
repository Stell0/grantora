from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest

from grantora.adapters import (
    AgentContext,
    ApplicationContext,
    CapabilityContext,
    InvocationContext,
    MockAdapter,
    NethVoicePhonebookAdapter,
    NextcloudFilesAdapter,
    SecretMaterial,
    UserContext,
    WorkspaceContext,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_mock_adapter_returns_phonebook_output_without_network() -> None:
    result = await MockAdapter().invoke(
        capability_stub(adapter_id="mock", provider_type="mock"),
        {"query": "Mario", "limit": 10},
        invocation_context(provider_type="mock", base_url=None),
        SecretMaterial(secret_type="bearer_token", value="mock-token"),
    )

    assert result.status == "ok"
    assert result.data == {"contacts": []}
    assert result.upstream_status is None


@pytest.mark.asyncio
async def test_nethvoice_phonebook_adapter_normalizes_mock_upstream_response() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            json={
                "contacts": [
                    {
                        "displayName": "Mario Rossi",
                        "number": "+3900112233",
                        "company": "Acme",
                        "email": "mario@example.test",
                    }
                ]
            },
        )

    adapter = NethVoicePhonebookAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.invoke(
        capability_stub(),
        {"query": "Mario", "limit": 10},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "ok"
    assert result.upstream_status == 200
    assert result.data == {
        "contacts": [
            {
                "display_name": "Mario Rossi",
                "phone": "+3900112233",
                "company": "Acme",
                "source": "nethvoice",
            }
        ]
    }
    assert len(seen_requests) == 1
    assert seen_requests[0].url.path == "/api/phonebook/search"
    assert seen_requests[0].url.params["query"] == "Mario"
    assert seen_requests[0].url.params["limit"] == "10"
    assert seen_requests[0].headers["authorization"] == "Bearer nethvoice-token"


@pytest.mark.asyncio
async def test_nethvoice_phonebook_adapter_matches_observed_provider_fixture() -> None:
    fixture_text = (FIXTURES_DIR / "nethvoice_phonebook_observed.json").read_text(encoding="utf-8")
    payload = json.loads(fixture_text)
    adapter = NethVoicePhonebookAdapter(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )

    result = await adapter.invoke(
        capability_stub(),
        {"query": "Mar", "limit": 10},
        invocation_context(),
        SecretMaterial(secret_type="api_key", value="fixture-api-key"),
    )

    assert "fixture-api-key" not in fixture_text
    assert result.status == "ok"
    assert result.data == {
        "contacts": [
            {
                "display_name": "Mario Rossi",
                "phone": "+3900112233",
                "company": "Acme SRL",
                "source": "nethvoice",
            },
            {
                "display_name": "Maria Bianchi",
                "phone": "+3900445566",
                "company": "Beta SPA",
                "source": "nethvoice",
            },
        ]
    }


@pytest.mark.asyncio
async def test_nethvoice_phonebook_adapter_trims_results_and_excludes_sensitive_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "results": [
                        {
                            "name": "Mario Rossi",
                            "phone": "+3900000001",
                            "company": "Acme",
                            "email": "mario@example.test",
                            "private_note": "hidden",
                        },
                        {
                            "firstName": "Maria",
                            "lastName": "Bianchi",
                            "phones": [{"number": "+3900000002"}],
                            "organization": "Beta",
                            "token": "hidden",
                        },
                        {
                            "name": "Marcello Verdi",
                            "phone": "+3900000003",
                            "company": "Gamma",
                        },
                    ]
                }
            },
        )

    adapter = NethVoicePhonebookAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.invoke(
        capability_stub(maximum=50),
        {"query": "Mar", "limit": 2},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "ok"
    assert result.data == {
        "contacts": [
            {
                "display_name": "Mario Rossi",
                "phone": "+3900000001",
                "company": "Acme",
                "source": "nethvoice",
            },
            {
                "display_name": "Maria Bianchi",
                "phone": "+3900000002",
                "company": "Beta",
                "source": "nethvoice",
            },
        ]
    }
    for contact in result.data["contacts"]:
        assert set(contact) == {"display_name", "phone", "company", "source"}


@pytest.mark.asyncio
async def test_nethvoice_phonebook_adapter_returns_empty_results() -> None:
    adapter = NethVoicePhonebookAdapter(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"contacts": []}))
    )

    result = await adapter.invoke(
        capability_stub(),
        {"query": "Nobody"},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "ok"
    assert result.data == {"contacts": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, "upstream_unauthorized", False),
        (403, "upstream_unauthorized", False),
        (404, "upstream_not_found", False),
        (429, "upstream_rate_limited", True),
        (503, "upstream_error", True),
    ],
)
async def test_nethvoice_phonebook_adapter_maps_upstream_status_errors(
    status_code: int,
    expected_code: str,
    retryable: bool,
) -> None:
    adapter = NethVoicePhonebookAdapter(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, json={"raw": "body"})
        )
    )

    result = await adapter.invoke(
        capability_stub(),
        {"query": "Mario"},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "error"
    assert result.error_code == expected_code
    assert result.upstream_status == status_code
    assert result.retryable is retryable
    assert result.data == {}


@pytest.mark.asyncio
async def test_nethvoice_phonebook_adapter_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow upstream", request=request)

    adapter = NethVoicePhonebookAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.invoke(
        capability_stub(),
        {"query": "Mario"},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "error"
    assert result.error_code == "upstream_timeout"
    assert result.upstream_status is None
    assert result.retryable is True


@pytest.mark.asyncio
async def test_nethvoice_phonebook_adapter_rejects_oversized_upstream_payload() -> None:
    adapter = NethVoicePhonebookAdapter(
        max_response_bytes=32,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "contacts": [
                        {
                            "displayName": "Mario Rossi",
                            "number": "+3900112233",
                            "company": "Acme",
                        }
                    ]
                },
            )
        ),
    )

    result = await adapter.invoke(
        capability_stub(),
        {"query": "Mario"},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "error"
    assert result.error_code == "upstream_payload_too_large"
    assert result.safe_message == "The upstream application response was too large"
    assert result.upstream_status == 200


@pytest.mark.asyncio
async def test_nethvoice_phonebook_adapter_maps_invalid_upstream_payload() -> None:
    adapter = NethVoicePhonebookAdapter(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"contacts": {"not": "a-list"}})
        )
    )

    result = await adapter.invoke(
        capability_stub(),
        {"query": "Mario"},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "error"
    assert result.error_code == "upstream_invalid_response"
    assert result.upstream_status == 200


@pytest.mark.asyncio
async def test_nethvoice_read_only_retry_is_bounded() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        if len(seen_requests) == 1:
            return httpx.Response(503, json={"raw": "hidden"})
        return httpx.Response(
            200,
            json={"contacts": [{"displayName": "Mario Rossi", "number": "+3900112233"}]},
        )

    adapter = NethVoicePhonebookAdapter(
        read_retry_attempts=2,
        transport=httpx.MockTransport(handler),
    )

    result = await adapter.invoke(
        capability_stub(risk_class="read_only"),
        {"query": "Mario"},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "ok"
    assert len(seen_requests) == 2


@pytest.mark.asyncio
async def test_side_effect_capability_is_not_retried_by_default() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(503, json={"raw": "hidden"})

    adapter = NethVoicePhonebookAdapter(
        read_retry_attempts=3,
        transport=httpx.MockTransport(handler),
    )

    result = await adapter.invoke(
        capability_stub(risk_class="side_effect"),
        {"query": "Mario"},
        invocation_context(),
        SecretMaterial(secret_type="bearer_token", value="nethvoice-token"),
    )

    assert result.status == "error"
    assert result.error_code == "upstream_error"
    assert len(seen_requests) == 1


@pytest.mark.asyncio
async def test_nextcloud_files_adapter_normalizes_mock_upstream_response() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            json={
                "ocs": {
                    "meta": {"status": "ok", "statuscode": 200},
                    "data": {
                        "entries": [
                            {
                                "title": "Quarterly report.pdf",
                                "resourceUrl": "https://cloud.example.test/remote.php/dav/files/alice/Documents/Quarterly%20report.pdf",
                                "attributes": {
                                    "mime_type": "application/pdf",
                                    "size": 4096,
                                    "mtime": 1717243200,
                                    "owner": "hidden",
                                },
                            }
                        ]
                    },
                }
            },
        )

    adapter = NextcloudFilesAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.invoke(
        nextcloud_capability_stub(maximum=25),
        {"query": "report", "limit": 10},
        invocation_context(provider_type="nextcloud", operation="files.search"),
        SecretMaterial(secret_type="basic_auth", value="alice:app-password"),
    )

    assert result.status == "ok"
    assert result.upstream_status == 200
    assert result.data == {
        "files": [
            {
                "path": "/Documents/Quarterly report.pdf",
                "display_name": "Quarterly report.pdf",
                "mime_type": "application/pdf",
                "size": 4096,
                "modified_at": "2024-06-01T12:00:00Z",
                "source": "nextcloud",
            }
        ]
    }
    assert len(seen_requests) == 1
    assert seen_requests[0].url.path == "/ocs/v2.php/search/providers/files/search"
    assert seen_requests[0].url.params["term"] == "report"
    assert seen_requests[0].url.params["limit"] == "10"
    assert seen_requests[0].headers["ocs-apirequest"] == "true"
    assert seen_requests[0].headers["authorization"] == "Basic YWxpY2U6YXBwLXBhc3N3b3Jk"


@pytest.mark.asyncio
async def test_nextcloud_files_adapter_returns_empty_results() -> None:
    adapter = NextcloudFilesAdapter(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ocs": {"data": {"entries": []}}})
        )
    )

    result = await adapter.invoke(
        nextcloud_capability_stub(),
        {"query": "missing"},
        invocation_context(provider_type="nextcloud", operation="files.search"),
        SecretMaterial(secret_type="basic_auth", value="alice:app-password"),
    )

    assert result.status == "ok"
    assert result.data == {"files": []}


@pytest.mark.asyncio
async def test_nextcloud_files_adapter_enforces_schema_limit_and_filters_fields() -> None:
    seen_limits = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_limits.append(request.url.params["limit"])
        return httpx.Response(
            200,
            json={
                "files": [
                    {"path": "/one.txt", "name": "one.txt", "mime_type": "text/plain"},
                    {"path": "/two.txt", "name": "two.txt", "mime_type": "text/plain"},
                    {"path": "/three.txt", "name": "three.txt", "mime_type": "text/plain"},
                ]
            },
        )

    adapter = NextcloudFilesAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.invoke(
        nextcloud_capability_stub(maximum=2),
        {"query": "txt", "limit": 99},
        invocation_context(provider_type="nextcloud", operation="files.search"),
        SecretMaterial(secret_type="bearer_token", value="nextcloud-token"),
    )

    assert result.status == "ok"
    assert seen_limits == ["2"]
    assert [item["path"] for item in result.data["files"]] == ["/one.txt", "/two.txt"]
    for file_item in result.data["files"]:
        assert set(file_item) == {
            "path",
            "display_name",
            "mime_type",
            "size",
            "modified_at",
            "source",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, "upstream_unauthorized", False),
        (403, "upstream_unauthorized", False),
        (404, "upstream_not_found", False),
        (429, "upstream_rate_limited", True),
        (503, "upstream_error", True),
    ],
)
async def test_nextcloud_files_adapter_maps_upstream_status_errors(
    status_code: int,
    expected_code: str,
    retryable: bool,
) -> None:
    adapter = NextcloudFilesAdapter(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status_code, json={"raw": "body"})
        )
    )

    result = await adapter.invoke(
        nextcloud_capability_stub(),
        {"query": "report"},
        invocation_context(provider_type="nextcloud", operation="files.search"),
        SecretMaterial(secret_type="basic_auth", value="alice:app-password"),
    )

    assert result.status == "error"
    assert result.error_code == expected_code
    assert result.upstream_status == status_code
    assert result.retryable is retryable
    assert result.data == {}


@pytest.mark.asyncio
async def test_nextcloud_files_adapter_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow upstream", request=request)

    adapter = NextcloudFilesAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.invoke(
        nextcloud_capability_stub(),
        {"query": "report"},
        invocation_context(provider_type="nextcloud", operation="files.search"),
        SecretMaterial(secret_type="basic_auth", value="alice:app-password"),
    )

    assert result.status == "error"
    assert result.error_code == "upstream_timeout"
    assert result.upstream_status is None
    assert result.retryable is True


@pytest.mark.asyncio
async def test_nextcloud_files_adapter_rejects_oversized_upstream_payload() -> None:
    adapter = NextcloudFilesAdapter(
        max_response_bytes=32,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"files": [{"path": "/big.txt", "name": "big.txt", "size": 1024}]},
            )
        ),
    )

    result = await adapter.invoke(
        nextcloud_capability_stub(),
        {"query": "big"},
        invocation_context(provider_type="nextcloud", operation="files.search"),
        SecretMaterial(secret_type="basic_auth", value="alice:app-password"),
    )

    assert result.status == "error"
    assert result.error_code == "upstream_payload_too_large"
    assert result.safe_message == "The upstream application response was too large"
    assert result.upstream_status == 200


@pytest.mark.asyncio
async def test_nextcloud_files_adapter_maps_invalid_upstream_payload() -> None:
    adapter = NextcloudFilesAdapter(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"files": {}}))
    )

    result = await adapter.invoke(
        nextcloud_capability_stub(),
        {"query": "report"},
        invocation_context(provider_type="nextcloud", operation="files.search"),
        SecretMaterial(secret_type="basic_auth", value="alice:app-password"),
    )

    assert result.status == "error"
    assert result.error_code == "upstream_invalid_response"
    assert result.upstream_status == 200


@pytest.mark.asyncio
async def test_nextcloud_health_checks_safe_endpoint_without_credentials() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(403, json={"message": "hidden"})

    adapter = NextcloudFilesAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.health(SimpleNamespace(base_url="https://cloud.example.test"))

    assert result.status == "ok"
    assert result.safe_message == "The upstream application is reachable but requires credentials"
    assert len(seen_requests) == 1
    assert seen_requests[0].url.path == "/ocs/v2.php/search/providers/files/search"
    assert "authorization" not in seen_requests[0].headers


@pytest.mark.asyncio
async def test_nethvoice_health_checks_safe_endpoint_without_credentials() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(401, json={"error": "redacted"})

    adapter = NethVoicePhonebookAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.health(SimpleNamespace(base_url="https://nethvoice.example.test"))

    assert result.status == "ok"
    assert result.safe_message == "The upstream application is reachable but requires credentials"
    assert len(seen_requests) == 1
    assert seen_requests[0].url.path == "/api/phonebook/search"
    assert seen_requests[0].url.params["limit"] == "1"
    assert "authorization" not in seen_requests[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_message"),
    [
        (404, "The upstream phonebook endpoint was not found"),
        (429, "The upstream application rate limit was reached"),
        (503, "The upstream application returned an error"),
    ],
)
async def test_nethvoice_health_maps_unavailable_responses_safely(
    status_code: int,
    expected_message: str,
) -> None:
    adapter = NethVoicePhonebookAdapter(
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code, text="hidden"))
    )

    result = await adapter.health(SimpleNamespace(base_url="https://nethvoice.example.test"))

    assert result.status == "error"
    assert result.safe_message == expected_message


@pytest.mark.asyncio
async def test_nethvoice_health_maps_timeout_safely() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow upstream", request=request)

    adapter = NethVoicePhonebookAdapter(transport=httpx.MockTransport(handler))

    result = await adapter.health(SimpleNamespace(base_url="https://nethvoice.example.test"))

    assert result.status == "error"
    assert result.safe_message == "The upstream application timed out"


def capability_stub(
    *,
    adapter_id: str = "nethvoice",
    provider_type: str = "nethvoice",
    maximum: int = 50,
    risk_class: str = "read_only",
) -> Any:
    return SimpleNamespace(
        id=f"{provider_type}.phonebook.search",
        provider_type=provider_type,
        adapter=adapter_id,
        operation="phonebook.search",
        risk_class=risk_class,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": maximum},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )


def nextcloud_capability_stub(*, maximum: int = 50, risk_class: str = "read_only") -> Any:
    return SimpleNamespace(
        id="nextcloud.files.search",
        provider_type="nextcloud",
        adapter="nextcloud",
        operation="files.search",
        risk_class=risk_class,
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": maximum},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )


def invocation_context(
    *,
    provider_type: str = "nethvoice",
    base_url: str | None = "https://nethvoice.example.test",
    operation: str = "phonebook.search",
) -> InvocationContext:
    return InvocationContext(
        request_id="req_adapter",
        workspace=WorkspaceContext(id=uuid4(), slug="acme"),
        agent=AgentContext(id=uuid4(), slug="runtime-agent"),
        user=UserContext(id=uuid4(), external_id="alice"),
        application=ApplicationContext(
            id=uuid4(),
            provider_type=provider_type,
            base_url=base_url,
        ),
        capability=CapabilityContext(
            id=f"{provider_type}.{operation}",
            operation=operation,
        ),
    )
