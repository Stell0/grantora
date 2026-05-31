from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
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
from grantora.main import create_app
from grantora.openapi import build_mcp_tool_list
from grantora.secrets import SecretCipher

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
        ]
    }
    assert "secret" not in response.text
    assert "https://mock.example.test" not in response.text

    missing_user_response = api_context.client.get(
        "/v1/capabilities?user=mallory",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert missing_user_response.status_code == 200
    assert missing_user_response.json() == {"capabilities": []}


def test_runtime_openapi_route_returns_runtime_schema_only(api_context: APIContext) -> None:
    add_runtime_records(api_context)

    response = api_context.client.get(
        "/v1/openapi.json",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert response.status_code == 200
    document = response.json()
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


def test_mcp_tool_list_generator_uses_stable_names_and_capability_mapping(
    api_context: APIContext,
) -> None:
    records = add_runtime_records(api_context)

    with api_context.database.session_factory() as session:
        capability = session.get(Capability, records.capability_id)
        assert capability is not None
        tool_list = build_mcp_tool_list([capability])

    assert tool_list == load_json_fixture("mcp_tool_list.json")


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


def load_json_fixture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


def runtime_openapi_contract(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "info": document["info"],
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
) -> None:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, records.workspace_id)
        application = session.get(ApplicationInstance, records.application_id)
        assert workspace is not None
        assert application is not None
        cipher = SecretCipher(api_context.settings.secret_encryption_key)
        session.add(
            Secret(
                workspace=workspace,
                application_instance=application,
                owner_type=owner_type,
                owner_id=owner_id,
                secret_type="bearer_token",
                encrypted_value=cipher.encrypt(value),
                status=status,
            )
        )
        session.commit()
