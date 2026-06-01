from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from grantora.auth import TOKEN_HASH_ALGORITHM, hash_token
from grantora.config import Settings
from grantora.db import Base, Database
from grantora.db.models import AdminCredential, Agent, Workspace
from grantora.main import create_app


@dataclass(frozen=True)
class APIContext:
    client: TestClient
    database: Database
    settings: Settings


@pytest.fixture()
def api_context(tmp_path: Path) -> Iterator[APIContext]:
    settings = make_test_settings(tmp_path)
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    app = create_app(settings=settings, database=database)

    with TestClient(app) as client:
        yield APIContext(client=client, database=database, settings=settings)


def test_admin_bootstrap_authentication_denies_invalid_and_allows_valid_tokens(
    api_context: APIContext,
) -> None:
    invalid_response = api_context.client.get(
        "/v1/admin/agents",
        headers=authorization_headers("wrong-admin-token"),
    )
    valid_response = api_context.client.get(
        "/v1/admin/agents",
        headers=authorization_headers("admin-token"),
    )

    assert invalid_response.status_code == 401
    assert invalid_response.json()["error"]["code"] == "admin_auth_invalid"
    assert valid_response.status_code == 200
    assert valid_response.json() == {"agents": [], "limit": 100, "offset": 0}


def test_admin_agent_creation_returns_token_once_and_persists_only_hash(
    api_context: APIContext,
) -> None:
    workspace_id = add_workspace(api_context, slug="acme")

    create_response = api_context.client.post(
        "/v1/admin/agents",
        headers=authorization_headers("admin-token"),
        json={
            "workspace_id": str(workspace_id),
            "slug": "hermes-alice",
            "display_name": "Hermes Alice",
        },
    )

    assert create_response.status_code == 201
    body = create_response.json()
    plaintext_token = body["token"]
    assert plaintext_token.startswith("grt_agent_")
    assert body["agent"] == {
        "id": body["agent"]["id"],
        "workspace_id": str(workspace_id),
        "slug": "hermes-alice",
        "display_name": "Hermes Alice",
        "status": "active",
    }

    list_response = api_context.client.get(
        "/v1/admin/agents",
        headers=authorization_headers("admin-token"),
    )

    assert list_response.status_code == 200
    assert "token" not in list_response.json()["agents"][0]
    assert plaintext_token not in list_response.text

    with api_context.database.session_factory() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == "hermes-alice"))

    assert agent is not None
    assert agent.token_hash_algorithm == TOKEN_HASH_ALGORITHM
    assert agent.token_hash != plaintext_token
    assert plaintext_token not in agent.token_hash


def test_runtime_agent_authentication_and_me_response(api_context: APIContext) -> None:
    workspace_id = add_workspace(api_context, slug="runtime-acme")
    active_token = "grt_agent_active"
    disabled_token = "grt_agent_disabled"
    add_agent(api_context, workspace_id, "active-agent", active_token)
    add_agent(api_context, workspace_id, "disabled-agent", disabled_token, status="disabled")

    missing_response = api_context.client.get("/v1/me")
    invalid_response = api_context.client.get(
        "/v1/me",
        headers=authorization_headers("grt_agent_wrong"),
    )
    disabled_response = api_context.client.get(
        "/v1/me",
        headers=authorization_headers(disabled_token),
    )
    valid_response = api_context.client.get(
        "/v1/me",
        headers=authorization_headers(active_token),
    )

    assert missing_response.status_code == 401
    assert missing_response.json()["error"]["code"] == "agent_auth_missing"
    assert invalid_response.status_code == 401
    assert invalid_response.json()["error"]["code"] == "agent_auth_invalid"
    assert disabled_response.status_code == 401
    assert disabled_response.json()["error"]["code"] == "agent_auth_invalid"
    assert valid_response.status_code == 200
    assert valid_response.json() == {
        "agent": {
            "id": valid_response.json()["agent"]["id"],
            "slug": "active-agent",
            "display_name": "Active Agent",
            "status": "active",
        },
        "workspace": {
            "id": str(workspace_id),
            "slug": "runtime-acme",
            "display_name": "runtime-acme Workspace",
            "status": "active",
        },
    }
    assert "token" not in valid_response.text
    assert "hash" not in valid_response.text


def test_disabled_workspace_denies_runtime_agent_authentication(
    api_context: APIContext,
) -> None:
    workspace_id = add_workspace(api_context, slug="disabled-runtime-acme", status="disabled")
    add_agent(api_context, workspace_id, "active-agent", "grt_agent_disabled_workspace")

    me_response = api_context.client.get(
        "/v1/me",
        headers=authorization_headers("grt_agent_disabled_workspace"),
    )
    capabilities_response = api_context.client.get(
        "/v1/capabilities?user=alice",
        headers=authorization_headers("grt_agent_disabled_workspace"),
    )

    assert me_response.status_code == 401
    assert me_response.json()["error"]["code"] == "agent_auth_invalid"
    assert capabilities_response.status_code == 401
    assert capabilities_response.json()["error"]["code"] == "agent_auth_invalid"


def test_agent_token_cannot_access_admin_endpoints(api_context: APIContext) -> None:
    workspace_id = add_workspace(api_context, slug="agent-admin-denied")
    add_agent(api_context, workspace_id, "runtime-agent", "grt_agent_runtime")

    response = api_context.client.get(
        "/v1/admin/workspaces",
        headers=authorization_headers("grt_agent_runtime"),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "admin_auth_invalid"


def test_database_admin_credentials_are_workspace_scoped(api_context: APIContext) -> None:
    own_workspace_id = add_workspace(api_context, slug="own-workspace")
    other_workspace_id = add_workspace(api_context, slug="other-workspace")
    add_admin_credential(
        api_context,
        subject="alice-admin",
        plaintext_token="scoped-admin-token",
        workspace_id=own_workspace_id,
    )

    list_response = api_context.client.get(
        "/v1/admin/workspaces",
        headers=authorization_headers("scoped-admin-token"),
    )
    own_user_response = api_context.client.post(
        "/v1/admin/users",
        headers=authorization_headers("scoped-admin-token"),
        json={
            "workspace_id": str(own_workspace_id),
            "external_id": "alice",
            "display_name": "Alice",
        },
    )
    cross_workspace_response = api_context.client.post(
        "/v1/admin/users",
        headers=authorization_headers("scoped-admin-token"),
        json={
            "workspace_id": str(other_workspace_id),
            "external_id": "mallory",
            "display_name": "Mallory",
        },
    )
    apisix_response = api_context.client.get(
        "/v1/admin/apisix/status",
        headers=authorization_headers("scoped-admin-token"),
    )

    assert list_response.status_code == 200
    assert [workspace["id"] for workspace in list_response.json()["workspaces"]] == [
        str(own_workspace_id)
    ]
    assert own_user_response.status_code == 201
    assert cross_workspace_response.status_code == 403
    assert cross_workspace_response.json()["error"]["code"] == "admin_scope_denied"
    assert apisix_response.status_code == 403
    assert apisix_response.json()["error"]["code"] == "admin_scope_denied"


def test_bootstrap_auth_still_works_when_oidc_is_disabled(api_context: APIContext) -> None:
    oidc_only_response = api_context.client.get(
        "/v1/admin/workspaces",
        headers={"X-Grantora-Admin-Subject": "ns8-admin"},
    )
    bootstrap_response = api_context.client.get(
        "/v1/admin/workspaces",
        headers={**authorization_headers("admin-token"), "X-Grantora-Admin-Subject": "ns8-admin"},
    )

    assert oidc_only_response.status_code == 401
    assert oidc_only_response.json()["error"]["code"] == "admin_auth_missing"
    assert bootstrap_response.status_code == 200


def test_oidc_admin_subject_is_optional_and_allowlisted(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'grantora.sqlite'}",
        environment="test",
        admin_bootstrap_token_hash=None,
        feature_oidc=True,
        oidc_admin_subjects="ns8-admin@example.test",
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    app = create_app(settings=settings, database=database)

    with TestClient(app) as client:
        allowed_response = client.get(
            "/v1/admin/workspaces",
            headers={"X-Grantora-Admin-Subject": "ns8-admin@example.test"},
        )
        denied_response = client.get(
            "/v1/admin/workspaces",
            headers={"X-Grantora-Admin-Subject": "mallory@example.test"},
        )

    assert allowed_response.status_code == 200
    assert denied_response.status_code == 401
    assert denied_response.json()["error"]["code"] == "admin_auth_invalid"


def make_test_settings(tmp_path: Path) -> Settings:
    pepper = "test-token-pepper"
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'grantora.sqlite'}",
        environment="test",
        agent_token_pepper=pepper,
        admin_bootstrap_token_hash=hash_token("admin-token", pepper),
    )


def authorization_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def add_workspace(api_context: APIContext, slug: str, status: str = "active") -> UUID:
    with api_context.database.session_factory() as session:
        workspace = Workspace(slug=slug, display_name=f"{slug} Workspace", status=status)
        session.add(workspace)
        session.commit()
        return workspace.id


def add_agent(
    api_context: APIContext,
    workspace_id: UUID,
    slug: str,
    plaintext_token: str,
    status: str = "active",
) -> UUID:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, workspace_id)
        assert workspace is not None
        agent = Agent(
            workspace=workspace,
            slug=slug,
            display_name=slug.replace("-", " ").title(),
            token_hash=hash_token(plaintext_token, api_context.settings.agent_token_pepper),
            token_hash_algorithm=TOKEN_HASH_ALGORITHM,
            status=status,
        )
        session.add(agent)
        session.commit()
        return agent.id


def add_admin_credential(
    api_context: APIContext,
    *,
    subject: str,
    plaintext_token: str,
    workspace_id: UUID | None,
) -> UUID:
    with api_context.database.session_factory() as session:
        workspace = session.get(Workspace, workspace_id) if workspace_id is not None else None
        credential = AdminCredential(
            subject=subject,
            token_hash=hash_token(plaintext_token, api_context.settings.agent_token_pepper),
            token_hash_algorithm=TOKEN_HASH_ALGORITHM,
            workspace=workspace,
        )
        session.add(credential)
        session.commit()
        return credential.id
