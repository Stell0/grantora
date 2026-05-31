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
from grantora.db.models import Agent, Workspace
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


def add_workspace(api_context: APIContext, slug: str) -> UUID:
    with api_context.database.session_factory() as session:
        workspace = Workspace(slug=slug, display_name=f"{slug} Workspace")
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
