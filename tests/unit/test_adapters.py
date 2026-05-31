from __future__ import annotations

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
    SecretMaterial,
    UserContext,
    WorkspaceContext,
)


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


def capability_stub(
    *,
    adapter_id: str = "nethvoice",
    provider_type: str = "nethvoice",
    maximum: int = 50,
) -> Any:
    return SimpleNamespace(
        id=f"{provider_type}.phonebook.search",
        provider_type=provider_type,
        adapter=adapter_id,
        operation="phonebook.search",
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
            id=f"{provider_type}.phonebook.search",
            operation="phonebook.search",
        ),
    )
