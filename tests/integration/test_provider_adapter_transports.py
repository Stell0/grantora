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
    NethVoicePhonebookAdapter,
    NextcloudFilesAdapter,
    SecretMaterial,
    UserContext,
    WorkspaceContext,
)

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).parents[1] / "unit" / "fixtures"


@pytest.mark.asyncio
async def test_real_provider_adapters_run_against_mock_http_transports() -> None:
    nethvoice_payload = load_fixture("nethvoice_phonebook_observed.json")
    nextcloud_payload = load_fixture("nextcloud_files_search_ocs.json")

    nethvoice = NethVoicePhonebookAdapter(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=nethvoice_payload))
    )
    nextcloud = NextcloudFilesAdapter(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=nextcloud_payload))
    )

    nethvoice_result = await nethvoice.invoke(
        capability_stub("nethvoice.phonebook.search", "nethvoice", "phonebook.search"),
        {"query": "Mar", "limit": 2},
        invocation_context("nethvoice", "phonebook.search", "https://nethvoice.example.test"),
        SecretMaterial(secret_type="bearer_token", value="fixture-token"),
    )
    nextcloud_result = await nextcloud.invoke(
        capability_stub("nextcloud.files.search", "nextcloud", "files.search"),
        {"query": "report", "limit": 2},
        invocation_context("nextcloud", "files.search", "https://cloud.example.test"),
        SecretMaterial(secret_type="basic_auth", value="alice:fixture-password"),
    )

    assert nethvoice_result.status == "ok"
    assert nethvoice_result.data["contacts"][0] == {
        "display_name": "Mario Rossi",
        "phone": "+3900112233",
        "company": "Acme SRL",
        "source": "nethvoice",
    }
    assert nextcloud_result.status == "ok"
    assert nextcloud_result.data["files"][0] == {
        "path": "/Documents/Quarterly report.pdf",
        "display_name": "Quarterly report.pdf",
        "mime_type": "application/pdf",
        "size": 4096,
        "modified_at": "2024-06-01T12:00:00Z",
        "source": "nextcloud",
    }


def capability_stub(capability_id: str, provider_type: str, operation: str) -> Any:
    return SimpleNamespace(
        id=capability_id,
        provider_type=provider_type,
        adapter=provider_type,
        operation=operation,
        risk_class="read_only",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )


def invocation_context(provider_type: str, operation: str, base_url: str) -> InvocationContext:
    return InvocationContext(
        request_id="req_adapter_it",
        workspace=WorkspaceContext(id=uuid4(), slug="acme"),
        agent=AgentContext(id=uuid4(), slug="runtime-agent"),
        user=UserContext(id=uuid4(), external_id="alice"),
        application=ApplicationContext(id=uuid4(), provider_type=provider_type, base_url=base_url),
        capability=CapabilityContext(id=f"{provider_type}.{operation}", operation=operation),
    )


def load_fixture(filename: str) -> dict[str, Any]:
    fixture_text = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
    assert "fixture-token" not in fixture_text
    assert "fixture-password" not in fixture_text
    return json.loads(fixture_text)
