from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import select

from grantora.adapters import AdapterResult, HealthResult, InvocationContext, SecretMaterial
from grantora.auth import TOKEN_HASH_ALGORITHM, hash_token
from grantora.config import Settings
from grantora.db import Base, Database
from grantora.db.models import (
    Agent,
    ApplicationInstance,
    AuditEvent,
    Binding,
    Capability,
    Permission,
    Role,
    RolePermission,
    Secret,
    UsageEvent,
    User,
    Workspace,
)
from grantora.logging import JsonLogFormatter
from grantora.main import create_app
from grantora.openapi import build_mcp_tool_list
from grantora.secrets import SecretCipher
from grantora.secrets.stores import stored_external_secret_reference

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class APIContext:
    client: TestClient
    database: Database
    settings: Settings
    adapter: RecordingAdapter


@dataclass(frozen=True)
class RuntimeRecords:
    workspace_id: UUID
    application_id: UUID
    agent_id: UUID
    user_id: UUID
    capability_id: str
    role_id: UUID


class RecordingAdapter:
    id = "recording"
    provider_type = "mock"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.next_result = AdapterResult.ok({"contacts": []}, usage_units=2)

    async def invoke(
        self,
        capability: Capability,
        input_data: dict[str, Any],
        context: InvocationContext,
        secret: SecretMaterial,
    ) -> AdapterResult:
        self.calls.append(
            {
                "capability_id": capability.id,
                "input": input_data,
                "context": context,
                "secret_type": secret.secret_type,
                "secret_value": secret.value,
            }
        )
        return self.next_result

    async def health(self, application: ApplicationInstance) -> HealthResult:
        return HealthResult(status="ok")


@pytest.fixture()
def api_context(tmp_path: Path) -> Iterator[APIContext]:
    settings = make_test_settings(tmp_path)
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    app = create_app(settings=settings, database=database)
    adapter = RecordingAdapter()
    app.state.adapters.register(adapter)

    with TestClient(app) as client:
        yield APIContext(client=client, database=database, settings=settings, adapter=adapter)


def test_capability_discovery_returns_only_allowed_safe_metadata(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_unbound_capability(api_context, records)
    add_disabled_capability_with_binding(api_context, records)
    add_bound_capability_without_invoke_permission(api_context, records)

    response = api_context.client.get(
        "/v1/capabilities?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "capabilities": [
            {
                "id": "mock.phonebook.search",
                "name": "Search phonebook",
                "version": 1,
                "provider_type": "mock",
                "operation": "phonebook.search",
                "auth_mode": "user",
                "risk_class": "read_only",
                "input_schema": phonebook_input_schema(),
                "output_schema": phonebook_output_schema(),
                "status": "active",
            }
        ],
        "limit": 100,
        "offset": 0,
    }
    assert "secret" not in response.text
    assert "https://mock.example.test" not in response.text

    missing_user_response = api_context.client.get(
        "/v1/capabilities?user=mallory",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert missing_user_response.status_code == 200
    assert missing_user_response.json() == {"capabilities": [], "limit": 100, "offset": 0}


def test_capability_discovery_is_paginated(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_second_bound_capability(api_context, records)

    response = api_context.client.get(
        "/v1/capabilities?user=alice&limit=1&offset=1",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "capabilities": [
            {
                "id": "mock.phonebook.search.extra",
                "name": "Search extra phonebook",
                "version": 1,
                "provider_type": "mock",
                "operation": "phonebook.search.extra",
                "auth_mode": "user",
                "risk_class": "read_only",
                "input_schema": phonebook_input_schema(),
                "output_schema": phonebook_output_schema(),
                "status": "active",
            }
        ],
        "limit": 1,
        "offset": 1,
    }


def test_admin_risk_capability_is_not_runtime_visible_or_invokable(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_admin_risk_capability(api_context, records)
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    discovery_response = api_context.client.get(
        "/v1/capabilities?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    invoke_response = api_context.client.post(
        "/v1/invoke/mock.admin.maintenance",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_admin_risk_denied",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert discovery_response.status_code == 200
    assert [capability["id"] for capability in discovery_response.json()["capabilities"]] == [
        "mock.phonebook.search"
    ]
    assert invoke_response.status_code == 403
    assert invoke_response.json()["error"]["code"] == "capability_denied"
    assert api_context.adapter.calls == []


def test_runtime_openapi_route_returns_runtime_schema_only(api_context: APIContext) -> None:
    add_runtime_records(api_context)

    response = api_context.client.get(
        "/v1/openapi.json",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert response.status_code == 200
    document = response.json()
    assert document["servers"] == [{"url": api_context.settings.public_base_url}]
    assert all(not path.startswith("/v1/admin") for path in document["paths"])
    assert "/healthz" not in document["paths"]
    assert runtime_openapi_contract(document) == load_json_fixture("runtime_openapi_contract.json")


def test_filtered_capability_openapi_matches_allowed_capability_contract(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_unbound_capability(api_context, records)
    add_disabled_capability_with_binding(api_context, records)
    add_bound_capability_without_invoke_permission(api_context, records)

    response = api_context.client.get(
        "/v1/capabilities/openapi.json?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert response.status_code == 200
    assert response.json() == load_json_fixture("filtered_capability_openapi.json")
    assert "mock.phonebook.unbound" not in response.text
    assert "mock.phonebook.disabled" not in response.text
    assert "mock.phonebook.write" not in response.text
    assert "https://mock.example.test" not in response.text

    missing_user_response = api_context.client.get(
        "/v1/capabilities/openapi.json?user=mallory",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert missing_user_response.status_code == 200
    assert missing_user_response.json()["paths"] == {}


def test_mcp_tools_endpoint_matches_filtered_capability_set(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_unbound_capability(api_context, records)
    add_disabled_capability_with_binding(api_context, records)
    add_bound_capability_without_invoke_permission(api_context, records)

    tools_response = api_context.client.get(
        "/v1/mcp/tools?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    openapi_response = api_context.client.get(
        "/v1/capabilities/openapi.json?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert tools_response.status_code == 200
    assert openapi_response.status_code == 200
    assert tools_response.json() == load_json_fixture("mcp_tool_list.json")
    assert mcp_tool_capability_map(tools_response.json()) == openapi_tool_capability_map(
        openapi_response.json()
    )
    assert "mock.phonebook.unbound" not in tools_response.text
    assert "mock.phonebook.disabled" not in tools_response.text
    assert "mock.phonebook.write" not in tools_response.text
    assert "https://mock.example.test" not in tools_response.text

    missing_user_response = api_context.client.get(
        "/v1/mcp/tools?user=mallory",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert missing_user_response.status_code == 200
    assert missing_user_response.json() == {"tools": []}


def test_runtime_usage_me_is_scoped_to_authenticated_agent(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    invocation_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_usage_me"},
        json={"user": "alice", "input": {"query": "Mario", "limit": 5}},
    )
    add_other_agent_usage_event(api_context, records)

    response = api_context.client.get(
        "/v1/usage/me?status=success&limit=10&offset=0",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert invocation_response.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert [event["agent_id"] for event in body["usage"]] == [str(records.agent_id)]
    assert body["usage"][0]["user_id"] == str(records.user_id)
    assert body["usage"][0]["capability_id"] == records.capability_id
    assert body["summaries"] == [
        {
            "workspace_id": str(records.workspace_id),
            "agent_id": str(records.agent_id),
            "user_id": str(records.user_id),
            "capability_id": records.capability_id,
            "status": "success",
            "events": 1,
            "total_units": 2,
        }
    ]


def test_mcp_tool_list_generator_uses_stable_names_and_capability_mapping(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)

    with api_context.database.session_factory() as session:
        capability = session.get(Capability, records.capability_id)
        assert capability is not None
        tool_list = build_mcp_tool_list([capability])

    assert tool_list == load_json_fixture("mcp_tool_list.json")


def test_mcp_tool_names_are_stable_and_unique_when_capability_ids_collide(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_colliding_bound_capability(api_context, records)
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    tools_response = api_context.client.get(
        "/v1/mcp/tools?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    openapi_response = api_context.client.get(
        "/v1/capabilities/openapi.json?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    call_response = api_context.client.post(
        "/v1/mcp/call",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_mcp_collision",
        },
        json={
            "user": "alice",
            "name": "mock_phonebook_search_f3b0ae3b",
            "arguments": {"query": "Mario", "limit": 5},
        },
    )

    assert tools_response.status_code == 200
    assert openapi_response.status_code == 200
    assert call_response.status_code == 200
    assert [tool["name"] for tool in tools_response.json()["tools"]] == [
        "mock_phonebook_search_8db26d62",
        "mock_phonebook_search_f3b0ae3b",
    ]
    assert mcp_tool_capability_map(tools_response.json()) == openapi_tool_capability_map(
        openapi_response.json()
    )
    assert call_response.json()["_meta"]["grantora/capability_id"] == records.capability_id
    assert api_context.adapter.calls[-1]["capability_id"] == records.capability_id


def test_capability_invocation_validates_authorization_and_reaches_adapter(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context, records, owner_type="workspace", owner_id=records.workspace_id, value="wrong"
    )
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_runtime_ok"},
        json={"user": "alice", "input": {"query": "Mario", "limit": 5}},
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "req_runtime_ok",
        "capability": "mock.phonebook.search",
        "status": "ok",
        "data": {"contacts": []},
    }
    assert api_context.adapter.calls == [
        {
            "capability_id": "mock.phonebook.search",
            "input": {"query": "Mario", "limit": 5},
            "context": api_context.adapter.calls[0]["context"],
            "secret_type": "bearer_token",
            "secret_value": "user-token",
        }
    ]
    assert api_context.adapter.calls[0]["context"].user.external_id == "alice"

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_runtime_ok")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "allow"
    assert audit_event.outcome == "success"
    assert audit_event.error_code is None
    assert usage_event is not None
    assert usage_event.status == "success"
    assert usage_event.units == 2


def test_mcp_tool_call_maps_to_capability_invocation(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/mcp/call",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_mcp_call"},
        json={
            "user": "alice",
            "name": "mock_phonebook_search",
            "arguments": {"query": "Mario", "limit": 5},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "content": [{"type": "text", "text": '{"contacts":[]}'}],
        "structuredContent": {"contacts": []},
        "isError": False,
        "_meta": {
            "grantora/request_id": "req_mcp_call",
            "grantora/capability_id": "mock.phonebook.search",
        },
    }
    assert api_context.adapter.calls == [
        {
            "capability_id": "mock.phonebook.search",
            "input": {"query": "Mario", "limit": 5},
            "context": api_context.adapter.calls[0]["context"],
            "secret_type": "bearer_token",
            "secret_value": "user-token",
        }
    ]
    assert api_context.adapter.calls[0]["context"].user.external_id == "alice"

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_mcp_call")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "allow"
    assert audit_event.outcome == "success"
    assert audit_event.error_code is None
    assert usage_event is not None
    assert usage_event.status == "success"
    assert usage_event.units == 2


def test_mcp_tool_call_denies_unknown_tool_and_records_events(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/mcp/call",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_mcp_denied"},
        json={
            "user": "alice",
            "name": "mock_phonebook_unbound",
            "arguments": {"query": "Mario"},
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "capability_denied",
        "message": "Capability is not allowed for this agent and user",
    }
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_mcp_denied")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == "mock_phonebook_unbound")
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert audit_event.outcome == "error"
    assert audit_event.error_code == "capability_denied"
    assert audit_event.capability_id == "mock_phonebook_unbound"
    assert usage_event is not None
    assert usage_event.status == "denied"


def test_builtin_mock_adapter_invocation_uses_default_registry(api_context: APIContext) -> None:
    records = add_runtime_records(api_context, adapter_id="mock")
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_builtin_mock",
        },
        json={"user": "alice", "input": {"query": "Mario", "limit": 5}},
    )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "req_builtin_mock",
        "capability": "mock.phonebook.search",
        "status": "ok",
        "data": {"contacts": []},
    }
    assert api_context.adapter.calls == []


def test_capability_invocation_is_denied_without_binding_and_records_events(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_user(api_context, records.workspace_id, "bob", "Bob")
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_denied"},
        json={"user": "bob", "input": {"query": "Mario"}},
    )

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "capability_denied",
        "message": "Capability is not allowed for this agent and user",
    }
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_denied")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert audit_event.outcome == "error"
    assert audit_event.error_code == "capability_denied"
    assert usage_event is not None
    assert usage_event.status == "denied"


def test_capability_invocation_requires_describe_and_invoke_permissions(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    remove_role_permission(api_context, records, "capability.describe")
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    discovery_response = api_context.client.get(
        "/v1/capabilities?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    invoke_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_missing_describe",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert discovery_response.status_code == 200
    assert discovery_response.json()["capabilities"] == []
    assert invoke_response.status_code == 403
    assert invoke_response.json()["error"] == {
        "code": "capability_denied",
        "message": "Capability is not allowed for this agent and user",
    }
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_missing_describe")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert audit_event.error_code == "capability_denied"
    assert usage_event is not None
    assert usage_event.status == "denied"


def test_capability_invocation_requires_risk_specific_invoke_permission(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_bound_capability_without_invoke_permission(api_context, records)
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.write",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_missing_invoke_permission",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "capability_denied"
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_missing_invoke_permission")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == "mock.phonebook.write")
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert audit_event.error_code == "capability_denied"
    assert usage_event is not None
    assert usage_event.status == "denied"


def test_disabled_user_is_hidden_denied_and_recorded(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    set_user_status(api_context, records, "disabled")
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    discovery_response = api_context.client.get(
        "/v1/capabilities?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    openapi_response = api_context.client.get(
        "/v1/capabilities/openapi.json?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    tools_response = api_context.client.get(
        "/v1/mcp/tools?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    invoke_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_disabled_user",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert discovery_response.status_code == 200
    assert discovery_response.json()["capabilities"] == []
    assert openapi_response.status_code == 200
    assert openapi_response.json()["paths"] == {}
    assert tools_response.status_code == 200
    assert tools_response.json() == {"tools": []}
    assert invoke_response.status_code == 403
    assert invoke_response.json()["error"]["code"] == "capability_denied"
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_disabled_user")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert audit_event.user_id == records.user_id
    assert usage_event is not None
    assert usage_event.status == "denied"
    assert usage_event.user_id == records.user_id


def test_disabled_binding_is_hidden_denied_and_recorded(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    set_binding_status(api_context, records, "disabled")
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    discovery_response = api_context.client.get(
        "/v1/capabilities?user=alice",
        headers=authorization_headers("grt_agent_runtime"),
    )
    invoke_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_disabled_binding",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert discovery_response.status_code == 200
    assert discovery_response.json()["capabilities"] == []
    assert invoke_response.status_code == 403
    assert invoke_response.json()["error"]["code"] == "capability_denied"
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_disabled_binding")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert audit_event.error_code == "capability_denied"
    assert usage_event is not None
    assert usage_event.status == "denied"


def test_disabled_capability_is_denied_and_audited(api_context: APIContext) -> None:
    records = add_runtime_records(api_context, capability_status="disabled")
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_disabled"},
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "capability_denied"
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_disabled")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert usage_event is not None
    assert usage_event.status == "denied"


def test_invalid_capability_input_returns_safe_error_and_records_usage(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_invalid"},
        json={"user": "alice", "input": {"limit": 100}},
    )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "invalid_capability_input",
        "message": "Capability input did not match the capability schema",
    }
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_invalid")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "allow"
    assert audit_event.outcome == "error"
    assert usage_event is not None
    assert usage_event.status == "error"


def test_missing_secret_fails_closed_and_is_recorded(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context, records, owner_type="workspace", owner_id=records.workspace_id, value="wrong"
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_no_secret"},
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 424
    assert response.json()["error"] == {
        "code": "secret_not_found",
        "message": "Required upstream secret was not found",
    }
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_no_secret")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert audit_event.error_code == "secret_not_found"
    assert usage_event is not None
    assert usage_event.status == "denied"


def test_unreadable_postgres_secret_fails_closed_before_adapter(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_unreadable_secret(api_context, records)

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_bad_secret"},
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 424
    assert response.json()["error"] == {
        "code": "secret_unavailable",
        "message": "Required upstream secret could not be used",
    }
    assert api_context.adapter.calls == []


def test_external_secret_reference_fails_closed_when_store_disabled(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context,
        records,
        owner_type="user",
        owner_id=records.user_id,
        value=stored_external_secret_reference("vault://grantora/alice-token"),
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_external_secret",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 424
    assert response.json()["error"]["code"] == "secret_unavailable"
    assert api_context.adapter.calls == []


def test_unsupported_runtime_auth_mode_fails_closed_before_adapter(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    set_capability_auth_mode(api_context, records, "admin")
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_auth_mode_closed",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 424
    assert response.json()["error"] == {
        "code": "capability_denied",
        "message": "Capability is not allowed for runtime invocation",
    }
    assert api_context.adapter.calls == []

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_auth_mode_closed")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "deny"
    assert audit_event.error_code == "capability_denied"
    assert usage_event is not None
    assert usage_event.status == "denied"


def test_revoked_secret_is_not_selected_for_invocation(api_context: APIContext) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context,
        records,
        owner_type="user",
        owner_id=records.user_id,
        value="revoked-token",
        status="revoked",
    )
    add_secret(
        api_context,
        records,
        owner_type="user",
        owner_id=records.user_id,
        value="active-token",
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_rotated"},
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 200
    assert api_context.adapter.calls[0]["secret_value"] == "active-token"


def test_admin_secret_rotation_revokes_old_secret_and_uses_replacement(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    old_secret_id = add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="old-token"
    )

    rotate_response = api_context.client.post(
        f"/v1/admin/secrets/{old_secret_id}/rotate",
        headers=authorization_headers("admin-token"),
        json={"value": "new-token"},
    )
    invoke_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_rotated_secret",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert rotate_response.status_code == 200
    rotation_body = rotate_response.json()
    assert rotation_body["revoked_secret"]["id"] == str(old_secret_id)
    assert rotation_body["revoked_secret"]["status"] == "revoked"
    assert rotation_body["secret"]["status"] == "active"
    assert "old-token" not in rotate_response.text
    assert "new-token" not in rotate_response.text
    assert invoke_response.status_code == 200
    assert api_context.adapter.calls[0]["secret_value"] == "new-token"

    with api_context.database.session_factory() as session:
        old_secret = session.get(Secret, old_secret_id)
        replacement = session.get(Secret, UUID(rotation_body["secret"]["id"]))

    assert old_secret is not None
    assert old_secret.status == "revoked"
    assert replacement is not None
    assert replacement.status == "active"


def test_adapter_error_is_returned_safely_and_records_error_usage(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context, records, owner_type="user", owner_id=records.user_id, value="user-token"
    )
    api_context.adapter.next_result = AdapterResult.error(
        "upstream_timeout",
        "The upstream application timed out",
        retryable=True,
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={**authorization_headers("grt_agent_runtime"), "X-Request-Id": "req_adapter_error"},
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "upstream_timeout",
        "message": "The upstream application timed out",
    }

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_adapter_error")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "allow"
    assert audit_event.outcome == "error"
    assert audit_event.error_code == "upstream_timeout"
    assert usage_event is not None
    assert usage_event.status == "error"


def test_invalid_adapter_output_is_returned_safely_and_not_leaked(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context,
        records,
        owner_type="user",
        owner_id=records.user_id,
        value="upstream-user-token",
    )
    api_context.adapter.next_result = AdapterResult.ok(
        {"contacts": [], "secret": "upstream-user-token"},
        upstream_status=200,
    )

    response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_adapter_invalid_output",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )

    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "adapter_invalid_response",
        "message": "Capability adapter returned invalid data",
    }
    assert "upstream-user-token" not in response.text

    with api_context.database.session_factory() as session:
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_adapter_invalid_output")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == records.capability_id)
        )

    assert audit_event is not None
    assert audit_event.decision == "allow"
    assert audit_event.outcome == "error"
    assert audit_event.error_code == "adapter_invalid_response"
    assert usage_event is not None
    assert usage_event.status == "error"


def test_runtime_metrics_cover_secret_resolution_success_denial_and_adapter_errors(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)
    success_request_labels = {
        "workspace": str(records.workspace_id),
        "agent": str(records.agent_id),
        "user": str(records.user_id),
        "capability": records.capability_id,
        "status": "200",
    }
    denied_labels = {
        "workspace": str(records.workspace_id),
        "reason": "capability_denied",
    }
    secret_not_found_labels = {
        "workspace": str(records.workspace_id),
        "provider": "mock",
        "result": "not_found",
    }
    secret_success_labels = {
        "workspace": str(records.workspace_id),
        "provider": "mock",
        "result": "success",
    }
    upstream_success_labels = {
        "workspace": str(records.workspace_id),
        "provider": "mock",
        "status": "200",
    }
    upstream_error_labels = {
        "workspace": str(records.workspace_id),
        "provider": "mock",
        "error_code": "upstream_timeout",
    }
    before_metrics = api_context.client.get("/metrics").text

    missing_secret_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_metrics_no_secret",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )
    add_secret(
        api_context,
        records,
        owner_type="user",
        owner_id=records.user_id,
        value="user-token",
    )
    api_context.adapter.next_result = AdapterResult.ok(
        {"contacts": []},
        usage_units=2,
        upstream_status=200,
    )
    success_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_metrics_success",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )
    add_user(api_context, records.workspace_id, "bob", "Bob")
    denied_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_metrics_denied",
        },
        json={"user": "bob", "input": {"query": "Mario"}},
    )
    api_context.adapter.next_result = AdapterResult.error(
        "upstream_timeout",
        "The upstream application timed out",
        upstream_status=504,
        retryable=True,
    )
    adapter_error_response = api_context.client.post(
        "/v1/invoke/mock.phonebook.search",
        headers={
            **authorization_headers("grt_agent_runtime"),
            "X-Request-Id": "req_metrics_error",
        },
        json={"user": "alice", "input": {"query": "Mario"}},
    )
    after_metrics = api_context.client.get("/metrics").text

    assert missing_secret_response.status_code == 424
    assert success_response.status_code == 200
    assert denied_response.status_code == 403
    assert adapter_error_response.status_code == 502
    assert metric_value(after_metrics, "grantora_requests_total", success_request_labels) == (
        metric_value(before_metrics, "grantora_requests_total", success_request_labels) + 1
    )
    assert metric_value(after_metrics, "grantora_authorization_denied_total", denied_labels) == (
        metric_value(before_metrics, "grantora_authorization_denied_total", denied_labels) + 1
    )
    assert metric_value(
        after_metrics,
        "grantora_secret_resolution_total",
        secret_not_found_labels,
    ) == (
        metric_value(
            before_metrics,
            "grantora_secret_resolution_total",
            secret_not_found_labels,
        )
        + 1
    )
    assert metric_value(
        after_metrics,
        "grantora_secret_resolution_total",
        secret_success_labels,
    ) == (
        metric_value(before_metrics, "grantora_secret_resolution_total", secret_success_labels) + 2
    )
    assert metric_value(
        after_metrics,
        "grantora_upstream_requests_total",
        upstream_success_labels,
    ) == (
        metric_value(
            before_metrics,
            "grantora_upstream_requests_total",
            upstream_success_labels,
        )
        + 1
    )
    assert metric_value(after_metrics, "grantora_upstream_errors_total", upstream_error_labels) == (
        metric_value(before_metrics, "grantora_upstream_errors_total", upstream_error_labels) + 1
    )
    assert "user-token" not in after_metrics


def test_runtime_denied_and_failed_invocations_emit_structured_logs(
    api_context: APIContext,
    caplog,
) -> None:
    records = add_runtime_records(api_context)
    add_secret(
        api_context,
        records,
        owner_type="user",
        owner_id=records.user_id,
        value="user-token",
    )
    add_user(api_context, records.workspace_id, "bob", "Bob")

    with caplog.at_level(logging.INFO, logger="grantora.runtime"):
        denied_response = api_context.client.post(
            "/v1/invoke/mock.phonebook.search",
            headers={
                **authorization_headers("grt_agent_runtime"),
                "X-Request-Id": "req_log_denied",
            },
            json={"user": "bob", "input": {"query": "Mario"}},
        )
        api_context.adapter.next_result = AdapterResult.error(
            "upstream_timeout",
            "The upstream application timed out",
            upstream_status=504,
            retryable=True,
        )
        error_response = api_context.client.post(
            "/v1/invoke/mock.phonebook.search",
            headers={
                **authorization_headers("grt_agent_runtime"),
                "X-Request-Id": "req_log_error",
            },
            json={"user": "alice", "input": {"query": "Mario"}},
        )

    assert denied_response.status_code == 403
    assert error_response.status_code == 502
    runtime_logs = [record for record in caplog.records if record.name == "grantora.runtime"]
    denied_log = next(record for record in runtime_logs if record.request_id == "req_log_denied")
    error_log = next(record for record in runtime_logs if record.request_id == "req_log_error")
    denied_payload = json.loads(JsonLogFormatter().format(denied_log))
    error_payload = json.loads(JsonLogFormatter().format(error_log))
    encoded_logs = json.dumps([denied_payload, error_payload], sort_keys=True)

    assert denied_payload["decision"] == "deny"
    assert denied_payload["outcome"] == "error"
    assert denied_payload["error_code"] == "capability_denied"
    assert denied_payload["usage_status"] == "denied"
    assert error_payload["decision"] == "allow"
    assert error_payload["outcome"] == "error"
    assert error_payload["error_code"] == "upstream_timeout"
    assert error_payload["usage_status"] == "error"
    assert "user-token" not in encoded_logs
    assert "Authorization" not in encoded_logs


def make_test_settings(tmp_path: Path) -> Settings:
    pepper = "test-token-pepper"
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'grantora.sqlite'}",
        environment="test",
        agent_token_pepper=pepper,
        admin_bootstrap_token_hash=hash_token("admin-token", pepper),
        secret_encryption_key=SecretCipher.generate_key(),
    )


def authorization_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def metric_value(metrics_text: str, metric_name: str, labels: dict[str, str]) -> float:
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            if sample.name == metric_name and sample.labels == labels:
                return float(sample.value)
    return 0.0


def load_json_fixture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


def runtime_openapi_contract(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "info": document["info"],
        "servers": document["servers"],
        "paths": {
            path: {
                method: {
                    "operationId": operation.get("operationId"),
                    "tags": operation.get("tags"),
                    "parameters": operation.get("parameters", []),
                    "requestBody": operation.get("requestBody"),
                    "responses": sorted(operation.get("responses", {}).keys()),
                }
                for method, operation in operations.items()
            }
            for path, operations in document["paths"].items()
        },
    }


def mcp_tool_capability_map(tool_list: dict[str, Any]) -> dict[str, str]:
    return {tool["name"]: tool["_meta"]["grantora/capability_id"] for tool in tool_list["tools"]}


def openapi_tool_capability_map(document: dict[str, Any]) -> dict[str, str]:
    return {
        operation["x-grantora-tool-name"]: operation["x-grantora-capability-id"]
        for operations in document["paths"].values()
        for operation in operations.values()
    }


def phonebook_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def phonebook_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"contacts": {"type": "array"}},
        "required": ["contacts"],
        "additionalProperties": False,
    }


def add_runtime_records(
    api_context: APIContext,
    *,
    capability_status: str = "active",
    adapter_id: str = "recording",
) -> RuntimeRecords:
    with api_context.database.session_factory() as session:
        workspace = Workspace(slug="acme", display_name="Acme SRL")
        application = ApplicationInstance(
            workspace=workspace,
            slug="mock-phone",
            display_name="Mock Phone",
            provider_type="mock",
            base_url="https://mock.example.test",
        )
        agent = Agent(
            workspace=workspace,
            slug="runtime-agent",
            display_name="Runtime Agent",
            token_hash=hash_token("grt_agent_runtime", api_context.settings.agent_token_pepper),
            token_hash_algorithm=TOKEN_HASH_ALGORITHM,
        )
        user = User(workspace=workspace, external_id="alice", display_name="Alice")
        capability = Capability(
            id="mock.phonebook.search",
            workspace=workspace,
            application_instance=application,
            name="Search phonebook",
            provider_type="mock",
            adapter=adapter_id,
            operation="phonebook.search",
            auth_mode="user",
            risk_class="read_only",
            input_schema=phonebook_input_schema(),
            output_schema=phonebook_output_schema(),
            status=capability_status,
        )
        role = Role(workspace=workspace, slug="reader", display_name="Reader")
        describe_permission = Permission(
            code="capability.describe",
            description="Describe capabilities",
        )
        invoke_permission = Permission(
            code="capability.invoke.read_only",
            description="Invoke read-only capabilities",
        )
        binding = Binding(
            workspace=workspace,
            agent=agent,
            user=user,
            capability=capability,
            role=role,
        )
        session.add_all(
            [
                workspace,
                application,
                agent,
                user,
                capability,
                role,
                describe_permission,
                invoke_permission,
                RolePermission(role=role, permission=describe_permission),
                RolePermission(role=role, permission=invoke_permission),
                binding,
            ]
        )
        session.commit()
        return RuntimeRecords(
            workspace_id=workspace.id,
            application_id=application.id,
            agent_id=agent.id,
            user_id=user.id,
            capability_id=capability.id,
            role_id=role.id,
        )


def add_unbound_capability(api_context: APIContext, records: RuntimeRecords) -> None:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        assert workspace is not None
        assert application is not None
        session.add(
            Capability(
                id="mock.phonebook.unbound",
                workspace=workspace,
                application_instance=application,
                name="Unbound phonebook",
                provider_type="mock",
                adapter="recording",
                operation="phonebook.unbound",
                auth_mode="user",
                risk_class="read_only",
                input_schema=phonebook_input_schema(),
                output_schema=phonebook_output_schema(),
            )
        )
        session.commit()


def add_disabled_capability_with_binding(api_context: APIContext, records: RuntimeRecords) -> None:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        agent = session.get(Agent, records.agent_id)
        user = session.get(User, records.user_id)
        role = session.get(Role, records.role_id)
        assert workspace is not None
        assert application is not None
        assert agent is not None
        assert user is not None
        assert role is not None
        capability = Capability(
            id="mock.phonebook.disabled",
            workspace=workspace,
            application_instance=application,
            name="Disabled phonebook",
            provider_type="mock",
            adapter="recording",
            operation="phonebook.disabled",
            auth_mode="user",
            risk_class="read_only",
            input_schema=phonebook_input_schema(),
            output_schema=phonebook_output_schema(),
            status="disabled",
        )
        binding = Binding(
            workspace=workspace,
            agent=agent,
            user=user,
            capability=capability,
            role=role,
        )
        session.add_all([capability, binding])
        session.commit()


def add_bound_capability_without_invoke_permission(
    api_context: APIContext,
    records: RuntimeRecords,
) -> None:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        agent = session.get(Agent, records.agent_id)
        user = session.get(User, records.user_id)
        role = session.get(Role, records.role_id)
        assert workspace is not None
        assert application is not None
        assert agent is not None
        assert user is not None
        assert role is not None
        capability = Capability(
            id="mock.phonebook.write",
            workspace=workspace,
            application_instance=application,
            name="Write phonebook",
            provider_type="mock",
            adapter="recording",
            operation="phonebook.write",
            auth_mode="user",
            risk_class="side_effect",
            input_schema=phonebook_input_schema(),
            output_schema=phonebook_output_schema(),
        )
        binding = Binding(
            workspace=workspace,
            agent=agent,
            user=user,
            capability=capability,
            role=role,
        )
        session.add_all([capability, binding])
        session.commit()


def add_second_bound_capability(api_context: APIContext, records: RuntimeRecords) -> None:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        agent = session.get(Agent, records.agent_id)
        user = session.get(User, records.user_id)
        role = session.get(Role, records.role_id)
        assert workspace is not None
        assert application is not None
        assert agent is not None
        assert user is not None
        assert role is not None
        capability = Capability(
            id="mock.phonebook.search.extra",
            workspace=workspace,
            application_instance=application,
            name="Search extra phonebook",
            provider_type="mock",
            adapter="recording",
            operation="phonebook.search.extra",
            auth_mode="user",
            risk_class="read_only",
            input_schema=phonebook_input_schema(),
            output_schema=phonebook_output_schema(),
        )
        binding = Binding(
            workspace=workspace,
            agent=agent,
            user=user,
            capability=capability,
            role=role,
        )
        session.add_all([capability, binding])
        session.commit()


def add_colliding_bound_capability(api_context: APIContext, records: RuntimeRecords) -> None:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        agent = session.get(Agent, records.agent_id)
        user = session.get(User, records.user_id)
        role = session.get(Role, records.role_id)
        assert workspace is not None
        assert application is not None
        assert agent is not None
        assert user is not None
        assert role is not None
        capability = Capability(
            id="mock-phonebook-search",
            workspace=workspace,
            application_instance=application,
            name="Search colliding phonebook",
            provider_type="mock",
            adapter="recording",
            operation="phonebook.search.colliding",
            auth_mode="user",
            risk_class="read_only",
            input_schema=phonebook_input_schema(),
            output_schema=phonebook_output_schema(),
        )
        binding = Binding(
            workspace=workspace,
            agent=agent,
            user=user,
            capability=capability,
            role=role,
        )
        session.add_all([capability, binding])
        session.commit()


def add_admin_risk_capability(api_context: APIContext, records: RuntimeRecords) -> None:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        agent = session.get(Agent, records.agent_id)
        user = session.get(User, records.user_id)
        role = session.get(Role, records.role_id)
        assert workspace is not None
        assert application is not None
        assert agent is not None
        assert user is not None
        assert role is not None
        capability = Capability(
            id="mock.admin.maintenance",
            workspace=workspace,
            application_instance=application,
            name="Admin maintenance",
            provider_type="mock",
            adapter="recording",
            operation="admin.maintenance",
            auth_mode="user",
            risk_class="admin",
            input_schema=phonebook_input_schema(),
            output_schema=phonebook_output_schema(),
        )
        binding = Binding(
            workspace=workspace,
            agent=agent,
            user=user,
            capability=capability,
            role=role,
        )
        session.add_all([capability, binding])
        session.commit()


def add_other_agent_usage_event(api_context: APIContext, records: RuntimeRecords) -> None:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        assert workspace is not None
        assert application is not None
        other_agent = Agent(
            workspace=workspace,
            slug="other-runtime-agent",
            display_name="Other Runtime Agent",
            token_hash=hash_token("grt_other_runtime", api_context.settings.agent_token_pepper),
            token_hash_algorithm=TOKEN_HASH_ALGORITHM,
        )
        session.add(other_agent)
        session.flush()
        session.add(
            UsageEvent(
                workspace=workspace,
                agent=other_agent,
                user_id=records.user_id,
                capability_id=records.capability_id,
                application_instance=application,
                status="success",
                units=99,
                latency_ms=1,
            )
        )
        session.commit()


def add_user(
    api_context: APIContext, workspace_id: UUID, external_id: str, display_name: str
) -> UUID:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        user = User(workspace=workspace, external_id=external_id, display_name=display_name)
        session.add(user)
        session.commit()
        return user.id


def add_secret(
    api_context: APIContext,
    records: RuntimeRecords,
    *,
    owner_type: str,
    owner_id: UUID,
    value: str,
    status: str = "active",
) -> UUID:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        assert workspace is not None
        assert application is not None
        cipher = SecretCipher(api_context.settings.secret_encryption_key)
        secret = Secret(
            workspace=workspace,
            application_instance=application,
            owner_type=owner_type,
            owner_id=owner_id,
            secret_type="bearer_token",
            encrypted_value=cipher.encrypt(value),
            status=status,
        )
        session.add(secret)
        session.commit()
        return secret.id


def add_unreadable_secret(api_context: APIContext, records: RuntimeRecords) -> UUID:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        assert workspace is not None
        assert application is not None
        secret = Secret(
            workspace=workspace,
            application_instance=application,
            owner_type="user",
            owner_id=records.user_id,
            secret_type="bearer_token",
            encrypted_value="not-a-valid-fernet-token",
        )
        session.add(secret)
        session.commit()
        return secret.id


def remove_role_permission(
    api_context: APIContext,
    records: RuntimeRecords,
    permission_code: str,
) -> None:
    with api_context.database.session_factory() as session:
        role_permission = session.get(RolePermission, (records.role_id, permission_code))
        assert role_permission is not None
        session.delete(role_permission)
        session.commit()


def set_user_status(api_context: APIContext, records: RuntimeRecords, status: str) -> None:
    with api_context.database.session_factory() as session:
        user = session.get(User, records.user_id)
        assert user is not None
        user.status = status
        session.commit()


def set_binding_status(api_context: APIContext, records: RuntimeRecords, status: str) -> None:
    with api_context.database.session_factory() as session:
        binding = session.scalar(
            select(Binding).where(
                Binding.workspace_id == records.workspace_id,
                Binding.agent_id == records.agent_id,
                Binding.user_id == records.user_id,
                Binding.capability_id == records.capability_id,
            )
        )
        assert binding is not None
        binding.status = status
        session.commit()


def set_capability_auth_mode(
    api_context: APIContext,
    records: RuntimeRecords,
    auth_mode: str,
) -> None:
    with api_context.database.session_factory() as session:
        capability = session.get(Capability, records.capability_id)
        assert capability is not None
        capability.auth_mode = auth_mode
        session.commit()
