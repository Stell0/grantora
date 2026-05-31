from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import undefer

from grantora.auth import hash_token
from grantora.config import Settings
from grantora.db import Base, Database
from grantora.db.models import AuditEvent, Secret
from grantora.main import create_app
from grantora.secrets import SecretCipher

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class APIContext:
    client: TestClient
    database: Database
    settings: Settings


@dataclass(frozen=True)
class BootstrapRecords:
    workspace_id: UUID
    application_id: UUID
    user_id: UUID
    capability_id: str
    role_id: UUID
    agent_id: UUID
    agent_token: str


@pytest.fixture()
def api_context(tmp_path: Path) -> Iterator[APIContext]:
    settings = make_test_settings(tmp_path)
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    app = create_app(settings=settings, database=database)

    with TestClient(app) as client:
        yield APIContext(client=client, database=database, settings=settings)


def test_admin_dynamic_bootstrap_flow_is_safe_and_runtime_visible(
    api_context: APIContext,
) -> None:
    workspace = post_admin(
        api_context,
        "/v1/admin/workspaces",
        {"slug": "acme", "display_name": "Acme SRL"},
        request_id="req_workspace_create",
    )["workspace"]
    workspace_id = UUID(workspace["id"])

    duplicate_workspace = api_context.client.post(
        "/v1/admin/workspaces",
        headers=authorization_headers("admin-token"),
        json={"slug": "acme", "display_name": "Duplicate"},
    )
    disabled_workspace = post_admin(
        api_context,
        "/v1/admin/workspaces",
        {"slug": "disabled", "display_name": "Disabled", "status": "disabled"},
    )["workspace"]

    default_workspaces = api_context.client.get(
        "/v1/admin/workspaces",
        headers=authorization_headers("admin-token"),
    )
    all_workspaces = api_context.client.get(
        "/v1/admin/workspaces?include_disabled=true",
        headers=authorization_headers("admin-token"),
    )

    assert duplicate_workspace.status_code == 409
    assert duplicate_workspace.json()["error"]["code"] == "workspace_conflict"
    assert [item["slug"] for item in default_workspaces.json()["workspaces"]] == ["acme"]
    assert {item["id"] for item in all_workspaces.json()["workspaces"]} == {
        str(workspace_id),
        disabled_workspace["id"],
    }

    missing_application = api_context.client.post(
        "/v1/admin/applications",
        headers=authorization_headers("admin-token"),
        json={
            "workspace_id": str(uuid4()),
            "slug": "nethvoice",
            "display_name": "NethVoice",
            "provider_type": "mock",
            "base_url": "https://mock.example.test",
        },
    )
    application = post_admin(
        api_context,
        "/v1/admin/applications",
        {
            "workspace_id": str(workspace_id),
            "slug": "mock-app",
            "display_name": "Mock App",
            "provider_type": "mock",
            "base_url": "https://mock.example.test",
        },
        request_id="req_application_create",
    )["application"]
    application_id = UUID(application["id"])

    assert missing_application.status_code == 404
    assert missing_application.json()["error"]["code"] == "workspace_not_found"
    assert application == {
        "id": str(application_id),
        "workspace_id": str(workspace_id),
        "slug": "mock-app",
        "display_name": "Mock App",
        "provider_type": "mock",
        "base_url": "https://mock.example.test",
        "status": "active",
    }
    assert api_context.client.get(
        f"/v1/admin/applications?workspace_id={workspace_id}",
        headers=authorization_headers("admin-token"),
    ).json()["applications"] == [application]

    alice = post_admin(
        api_context,
        "/v1/admin/users",
        {"workspace_id": str(workspace_id), "external_id": "alice", "display_name": "Alice"},
    )["user"]
    disabled_user = post_admin(
        api_context,
        "/v1/admin/users",
        {
            "workspace_id": str(workspace_id),
            "external_id": "disabled-alice",
            "display_name": "Disabled Alice",
            "status": "disabled",
        },
    )["user"]
    user_id = UUID(alice["id"])

    users_response = api_context.client.get(
        f"/v1/admin/users?workspace_id={workspace_id}",
        headers=authorization_headers("admin-token"),
    )
    all_users_response = api_context.client.get(
        f"/v1/admin/users?workspace_id={workspace_id}&include_disabled=true",
        headers=authorization_headers("admin-token"),
    )

    assert users_response.json()["users"] == [alice]
    assert {user["id"] for user in all_users_response.json()["users"]} == {
        str(user_id),
        disabled_user["id"],
    }

    invalid_schema_response = api_context.client.post(
        "/v1/admin/capabilities",
        headers=authorization_headers("admin-token"),
        json={
            **capability_payload(workspace_id, application_id),
            "id": "mock.invalid.schema",
            "input_schema": {"type": 12},
        },
    )
    other_workspace = post_admin(
        api_context,
        "/v1/admin/workspaces",
        {"slug": "other", "display_name": "Other"},
    )["workspace"]
    other_application = post_admin(
        api_context,
        "/v1/admin/applications",
        {
            "workspace_id": other_workspace["id"],
            "slug": "mock-app",
            "display_name": "Other Mock App",
            "provider_type": "mock",
            "base_url": "https://other.example.test",
        },
    )["application"]
    workspace_mismatch_response = api_context.client.post(
        "/v1/admin/capabilities",
        headers=authorization_headers("admin-token"),
        json=capability_payload(workspace_id, UUID(other_application["id"])),
    )
    capability = post_admin(
        api_context,
        "/v1/admin/capabilities",
        capability_payload(workspace_id, application_id),
        request_id="req_capability_create",
    )["capability"]

    assert invalid_schema_response.status_code == 422
    assert invalid_schema_response.json()["error"]["code"] == "capability_schema_invalid"
    assert workspace_mismatch_response.status_code == 422
    assert workspace_mismatch_response.json()["error"]["code"] == "application_workspace_mismatch"
    assert capability["id"] == "mock.phonebook.search"
    assert api_context.client.get(
        f"/v1/admin/capabilities?workspace_id={workspace_id}",
        headers=authorization_headers("admin-token"),
    ).json()["capabilities"] == [capability]

    unknown_permission_response = api_context.client.post(
        "/v1/admin/roles",
        headers=authorization_headers("admin-token"),
        json={
            "workspace_id": str(workspace_id),
            "slug": "bad-role",
            "display_name": "Bad Role",
            "permission_codes": ["capability.describe", "capability.invoke.unknown"],
        },
    )
    role = post_admin(
        api_context,
        "/v1/admin/roles",
        {
            "workspace_id": str(workspace_id),
            "slug": "phonebook-reader",
            "display_name": "Phonebook Reader",
            "permission_codes": ["capability.describe", "capability.invoke.read_only"],
        },
        request_id="req_role_create",
    )["role"]
    role_id = UUID(role["id"])
    other_role = post_admin(
        api_context,
        "/v1/admin/roles",
        {
            "workspace_id": other_workspace["id"],
            "slug": "other-reader",
            "display_name": "Other Reader",
            "permission_codes": ["capability.describe", "capability.invoke.read_only"],
        },
    )["role"]

    assert unknown_permission_response.status_code == 422
    assert unknown_permission_response.json()["error"]["code"] == "permission_unknown"
    permissions = api_context.client.get(
        "/v1/admin/permissions",
        headers=authorization_headers("admin-token"),
    ).json()["permissions"]

    assert role["permission_codes"] == ["capability.describe", "capability.invoke.read_only"]
    assert "capability.invoke.read_only" in [item["code"] for item in permissions]

    agent_response = post_admin(
        api_context,
        "/v1/admin/agents",
        {"workspace_id": str(workspace_id), "slug": "hermes-alice", "display_name": "Hermes Alice"},
        request_id="req_agent_create",
    )
    agent = agent_response["agent"]
    agent_id = UUID(agent["id"])
    agent_token = agent_response["token"]

    cross_workspace_binding = api_context.client.post(
        "/v1/admin/bindings",
        headers=authorization_headers("admin-token"),
        json={
            "workspace_id": str(workspace_id),
            "agent_id": str(agent_id),
            "user_id": str(user_id),
            "capability_id": "mock.phonebook.search",
            "role_id": other_role["id"],
        },
    )
    binding = post_admin(
        api_context,
        "/v1/admin/bindings",
        {
            "workspace_id": str(workspace_id),
            "agent_id": str(agent_id),
            "user_id": str(user_id),
            "capability_id": "mock.phonebook.search",
            "role_id": str(role_id),
        },
        request_id="req_binding_create",
    )["binding"]

    assert cross_workspace_binding.status_code == 422
    assert cross_workspace_binding.json()["error"]["code"] == "role_workspace_mismatch"
    assert binding["workspace_id"] == str(workspace_id)

    missing_secret_owner = api_context.client.post(
        "/v1/admin/secrets",
        headers=authorization_headers("admin-token"),
        json={
            "workspace_id": str(workspace_id),
            "application_instance_id": str(application_id),
            "owner_type": "user",
            "owner_id": str(uuid4()),
            "secret_type": "bearer_token",
            "value": "missing-owner-token",
        },
    )
    secret = post_admin(
        api_context,
        "/v1/admin/secrets",
        {
            "workspace_id": str(workspace_id),
            "application_instance_id": str(application_id),
            "owner_type": "user",
            "owner_id": str(user_id),
            "secret_type": "bearer_token",
            "value": "upstream-user-token",
        },
        request_id="req_secret_create",
    )["secret"]
    secrets_response = api_context.client.get(
        f"/v1/admin/secrets?workspace_id={workspace_id}",
        headers=authorization_headers("admin-token"),
    )

    assert missing_secret_owner.status_code == 404
    assert missing_secret_owner.json()["error"]["code"] == "user_not_found"
    assert "value" not in secret
    assert "encrypted_value" not in secret
    assert "upstream-user-token" not in secrets_response.text
    assert "encrypted_value" not in secrets_response.text

    with api_context.database.session_factory() as session:
        stored_secret = session.scalar(
            select(Secret)
            .options(undefer(Secret.encrypted_value))
            .where(Secret.id == UUID(secret["id"]))
        )
        admin_audit = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_agent_create")
        )

    assert stored_secret is not None
    assert stored_secret.encrypted_value != "upstream-user-token"
    assert "upstream-user-token" not in stored_secret.encrypted_value
    assert admin_audit is not None
    assert admin_audit.actor_type == "admin_bootstrap"
    assert admin_audit.workspace_id == workspace_id
    assert (
        resource_response_contract(
            workspace=workspace,
            application=application,
            user=alice,
            capability=capability,
            role=role,
            permission=permissions[0],
            agent=agent,
            binding=binding,
            secret=secret,
        )
        == load_json_fixture("admin_response_contract.json")["resources"]
    )

    visible_capabilities = api_context.client.get(
        "/v1/capabilities?user=alice",
        headers=authorization_headers(agent_token),
    )
    disabled_user_capabilities = api_context.client.get(
        "/v1/capabilities?user=disabled-alice",
        headers=authorization_headers(agent_token),
    )

    assert visible_capabilities.status_code == 200
    assert [item["id"] for item in visible_capabilities.json()["capabilities"]] == [
        "mock.phonebook.search"
    ]
    assert disabled_user_capabilities.status_code == 200
    assert disabled_user_capabilities.json() == {"capabilities": []}


def test_admin_audit_and_usage_queries_are_filtered_and_summarized(
    api_context: APIContext,
) -> None:
    records = bootstrap_runtime_records(api_context)
    bob = post_admin(
        api_context,
        "/v1/admin/users",
        {"workspace_id": str(records.workspace_id), "external_id": "bob", "display_name": "Bob"},
    )["user"]

    success_response = api_context.client.post(
        f"/v1/invoke/{records.capability_id}",
        headers={**authorization_headers(records.agent_token), "X-Request-Id": "req_usage_success"},
        json={"user": "alice", "input": {"query": "Mario", "limit": 5}},
    )
    denied_response = api_context.client.post(
        f"/v1/invoke/{records.capability_id}",
        headers={**authorization_headers(records.agent_token), "X-Request-Id": "req_usage_denied"},
        json={"user": "bob", "input": {"query": "Mario"}},
    )

    audit_response = api_context.client.get(
        f"/v1/admin/audit?workspace_id={records.workspace_id}"
        f"&capability_id={records.capability_id}&actor_type=agent",
        headers=authorization_headers("admin-token"),
    )
    denied_audit_response = api_context.client.get(
        f"/v1/admin/audit?workspace_id={records.workspace_id}&decision=deny",
        headers=authorization_headers("admin-token"),
    )
    usage_response = api_context.client.get(
        f"/v1/admin/usage?workspace_id={records.workspace_id}",
        headers=authorization_headers("admin-token"),
    )
    success_usage_response = api_context.client.get(
        f"/v1/admin/usage?workspace_id={records.workspace_id}&status=success",
        headers=authorization_headers("admin-token"),
    )

    assert success_response.status_code == 200
    assert denied_response.status_code == 403
    assert denied_response.json()["error"]["code"] == "capability_denied"
    assert audit_response.status_code == 200
    assert {event["request_id"] for event in audit_response.json()["audit"]} == {
        "req_usage_success",
        "req_usage_denied",
    }
    assert {event["actor_type"] for event in audit_response.json()["audit"]} == {"agent"}
    assert "upstream-user-token" not in audit_response.text
    assert denied_audit_response.status_code == 200
    assert [event["request_id"] for event in denied_audit_response.json()["audit"]] == [
        "req_usage_denied"
    ]

    usage_body = usage_response.json()
    assert usage_response.status_code == 200
    assert {event["status"] for event in usage_body["usage"]} == {"success", "denied"}
    assert {summary["status"]: summary["events"] for summary in usage_body["summaries"]} == {
        "success": 1,
        "denied": 1,
    }
    assert {summary["status"]: summary["total_units"] for summary in usage_body["summaries"]} == {
        "success": 1,
        "denied": 1,
    }
    assert "upstream-user-token" not in usage_response.text
    assert [event["status"] for event in success_usage_response.json()["usage"]] == ["success"]
    assert success_usage_response.json()["usage"][0]["user_id"] == str(records.user_id)
    assert bob["id"] in usage_response.text
    assert (
        query_response_contract(audit_response.json(), usage_body)
        == load_json_fixture("admin_response_contract.json")["queries"]
    )


def bootstrap_runtime_records(api_context: APIContext) -> BootstrapRecords:
    workspace = post_admin(
        api_context,
        "/v1/admin/workspaces",
        {"slug": f"workspace-{uuid4().hex[:8]}", "display_name": "Workspace"},
    )["workspace"]
    workspace_id = UUID(workspace["id"])
    application = post_admin(
        api_context,
        "/v1/admin/applications",
        {
            "workspace_id": str(workspace_id),
            "slug": "mock-app",
            "display_name": "Mock App",
            "provider_type": "mock",
            "base_url": "https://mock.example.test",
        },
    )["application"]
    application_id = UUID(application["id"])
    user = post_admin(
        api_context,
        "/v1/admin/users",
        {"workspace_id": str(workspace_id), "external_id": "alice", "display_name": "Alice"},
    )["user"]
    user_id = UUID(user["id"])
    capability = post_admin(
        api_context,
        "/v1/admin/capabilities",
        capability_payload(workspace_id, application_id),
    )["capability"]
    role = post_admin(
        api_context,
        "/v1/admin/roles",
        {
            "workspace_id": str(workspace_id),
            "slug": "phonebook-reader",
            "display_name": "Phonebook Reader",
            "permission_codes": ["capability.describe", "capability.invoke.read_only"],
        },
    )["role"]
    role_id = UUID(role["id"])
    agent_response = post_admin(
        api_context,
        "/v1/admin/agents",
        {"workspace_id": str(workspace_id), "slug": "hermes-alice", "display_name": "Hermes Alice"},
    )
    agent_id = UUID(agent_response["agent"]["id"])
    post_admin(
        api_context,
        "/v1/admin/bindings",
        {
            "workspace_id": str(workspace_id),
            "agent_id": str(agent_id),
            "user_id": str(user_id),
            "capability_id": capability["id"],
            "role_id": str(role_id),
        },
    )
    post_admin(
        api_context,
        "/v1/admin/secrets",
        {
            "workspace_id": str(workspace_id),
            "application_instance_id": str(application_id),
            "owner_type": "user",
            "owner_id": str(user_id),
            "secret_type": "bearer_token",
            "value": "upstream-user-token",
        },
    )
    return BootstrapRecords(
        workspace_id=workspace_id,
        application_id=application_id,
        user_id=user_id,
        capability_id=capability["id"],
        role_id=role_id,
        agent_id=agent_id,
        agent_token=agent_response["token"],
    )


def post_admin(
    api_context: APIContext,
    path: str,
    payload: dict[str, Any],
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    headers = authorization_headers("admin-token")
    if request_id is not None:
        headers["X-Request-Id"] = request_id
    response = api_context.client.post(path, headers=headers, json=payload)
    assert response.status_code in {200, 201}, response.text
    return response.json()


def capability_payload(workspace_id: UUID, application_id: UUID) -> dict[str, Any]:
    return {
        "id": "mock.phonebook.search",
        "workspace_id": str(workspace_id),
        "application_instance_id": str(application_id),
        "name": "Search phonebook",
        "version": 1,
        "provider_type": "mock",
        "adapter": "mock",
        "operation": "phonebook.search",
        "auth_mode": "user",
        "risk_class": "read_only",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"contacts": {"type": "array"}},
            "required": ["contacts"],
            "additionalProperties": False,
        },
    }


def resource_response_contract(
    *,
    workspace: dict[str, Any],
    application: dict[str, Any],
    user: dict[str, Any],
    capability: dict[str, Any],
    role: dict[str, Any],
    permission: dict[str, Any],
    agent: dict[str, Any],
    binding: dict[str, Any],
    secret: dict[str, Any],
) -> dict[str, Any]:
    return {
        "workspace": sorted(workspace),
        "application": sorted(application),
        "user": sorted(user),
        "capability": sorted(capability),
        "role": sorted(role),
        "role_permission_codes": role["permission_codes"],
        "permission": sorted(permission),
        "agent": sorted(agent),
        "binding": sorted(binding),
        "secret": sorted(secret),
    }


def query_response_contract(
    audit_body: dict[str, Any], usage_body: dict[str, Any]
) -> dict[str, Any]:
    return {
        "audit": sorted(audit_body["audit"][0]),
        "usage": sorted(usage_body["usage"][0]),
        "usage_summary": sorted(usage_body["summaries"][0]),
    }


def load_json_fixture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


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
