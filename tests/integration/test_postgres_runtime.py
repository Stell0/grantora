from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from grantora.auth import hash_token
from grantora.cli.demo_workflow import DemoSeedConfig, JSONDict, seed_demo
from grantora.config import Settings
from grantora.db import Database
from grantora.db.models import Agent, AuditEvent, UsageEvent, User, Workspace
from grantora.db.queries import list_active_capabilities_for_agent_user, role_grants_permission
from grantora.main import create_app
from grantora.secrets import SecretCipher

from .conftest import IsolatedPostgresSchema, table_names_for_schema

pytestmark = pytest.mark.integration


def test_alembic_upgrade_and_postgres_session_lifecycle(
    migrated_postgres_schema: IsolatedPostgresSchema,
) -> None:
    table_names = table_names_for_schema(migrated_postgres_schema)
    assert {"alembic_version", "workspaces", "agents", "usage_events"} <= table_names

    database = Database(settings_for_database(migrated_postgres_schema.database_url))
    database.ping()
    with database.session_factory() as session:
        workspace = Workspace(slug="postgres-it", display_name="PostgreSQL Integration")
        session.add(workspace)
        session.commit()

    with database.session_factory() as session:
        saved_workspace = session.scalar(select(Workspace).where(Workspace.slug == "postgres-it"))

    assert saved_workspace is not None
    assert saved_workspace.display_name == "PostgreSQL Integration"
    database.dispose()


def test_release_upgrade_from_previous_release_fixture_preserves_data_and_policy(
    isolated_postgres_schema: IsolatedPostgresSchema,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", isolated_postgres_schema.database_url)
    alembic_config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    fixture = PreviousReleaseFixture.create()

    command.upgrade(alembic_config, "202605310004")
    seed_previous_release_fixture(isolated_postgres_schema.database_url, fixture)

    command.upgrade(alembic_config, "head")

    table_names = table_names_for_schema(isolated_postgres_schema)
    database = Database(settings_for_database(isolated_postgres_schema.database_url))
    with database.session_factory() as session:
        workspace = session.get(Workspace, fixture.workspace_id)
        agent = session.get(Agent, fixture.agent_id)
        user = session.get(User, fixture.user_id)
        capabilities = list_active_capabilities_for_agent_user(
            session,
            fixture.workspace_id,
            fixture.agent_id,
            fixture.user_id,
        )
        audit_event = session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == "req_upgrade_fixture")
        )
        usage_event = session.scalar(
            select(UsageEvent).where(UsageEvent.capability_id == fixture.capability_id)
        )
        grants_read = role_grants_permission(
            session,
            fixture.role_id,
            "capability.invoke.read_only",
        )

    database.dispose()

    assert "admin_credentials" in table_names
    assert workspace is not None
    assert agent is not None
    assert user is not None
    assert [capability.id for capability in capabilities] == [fixture.capability_id]
    assert audit_event is not None
    assert usage_event is not None
    assert grants_read is True


def test_admin_api_bootstrap_and_runtime_invocation_use_postgres_records(
    migrated_postgres_schema: IsolatedPostgresSchema,
    tmp_path: Path,
) -> None:
    settings = settings_for_database(migrated_postgres_schema.database_url)
    database = Database(settings)
    app = create_app(settings=settings, database=database)

    with TestClient(app) as client:
        workflow_client = WorkflowClientForTestClient(client)
        seed_config = DemoSeedConfig(
            api_url="http://testserver",
            admin_token="admin-token",
            output_env_path=tmp_path / "demo.env",
            workspace_slug="postgres-runtime-it",
            capability_id="mock.phonebook.search.postgres_it",
            agent_slug="postgres-runtime-agent",
        )
        seed_result = seed_demo(workflow_client, seed_config)

        assert seed_result.agent_token is not None
        invoke_response = client.post(
            f"/v1/invoke/{seed_result.capability_id}",
            headers={
                "Authorization": f"Bearer {seed_result.agent_token}",
                "X-Request-Id": "req_postgres_runtime_ok",
            },
            json={"user": seed_config.user_external_id, "input": {"query": "Mario"}},
        )
        audit_response = client.get(
            f"/v1/admin/audit?workspace_id={seed_result.workspace_id}&actor_type=agent",
            headers={"Authorization": "Bearer admin-token"},
        )
        usage_response = client.get(
            f"/v1/admin/usage?workspace_id={seed_result.workspace_id}&status=success",
            headers={"Authorization": "Bearer admin-token"},
        )

    assert invoke_response.status_code == 200
    assert invoke_response.json()["data"] == {"contacts": []}
    assert any(
        event["request_id"] == "req_postgres_runtime_ok" for event in audit_response.json()["audit"]
    )
    assert any(
        event["capability_id"] == seed_result.capability_id
        for event in usage_response.json()["usage"]
    )


@dataclass(frozen=True)
class PreviousReleaseFixture:
    workspace_id: UUID
    application_id: UUID
    agent_id: UUID
    user_id: UUID
    role_id: UUID
    binding_id: UUID
    audit_id: UUID
    usage_id: UUID
    capability_id: str

    @classmethod
    def create(cls) -> PreviousReleaseFixture:
        return cls(
            workspace_id=uuid4(),
            application_id=uuid4(),
            agent_id=uuid4(),
            user_id=uuid4(),
            role_id=uuid4(),
            binding_id=uuid4(),
            audit_id=uuid4(),
            usage_id=uuid4(),
            capability_id="mock.phonebook.search.upgrade_fixture",
        )


def seed_previous_release_fixture(database_url: str, fixture: PreviousReleaseFixture) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    insert into workspaces (id, slug, display_name, status)
                    values (:id, 'upgrade-fixture', 'Upgrade Fixture', 'active')
                    """
                ),
                {"id": fixture.workspace_id},
            )
            connection.execute(
                text(
                    """
                    insert into application_instances
                        (id, workspace_id, slug, display_name, provider_type, base_url, status)
                    values
                        (:id, :workspace_id, 'mock-upgrade', 'Mock Upgrade', 'mock', null, 'active')
                    """
                ),
                {"id": fixture.application_id, "workspace_id": fixture.workspace_id},
            )
            connection.execute(
                text(
                    """
                    insert into agents
                        (id, workspace_id, slug, display_name, token_hash,
                         token_hash_algorithm, status)
                    values
                        (:id, :workspace_id, 'upgrade-agent', 'Upgrade Agent',
                         'hmac-sha256:upgrade-agent', 'hmac-sha256', 'active')
                    """
                ),
                {"id": fixture.agent_id, "workspace_id": fixture.workspace_id},
            )
            connection.execute(
                text(
                    """
                    insert into users (id, workspace_id, external_id, display_name, status)
                    values (:id, :workspace_id, 'alice', 'Alice Upgrade', 'active')
                    """
                ),
                {"id": fixture.user_id, "workspace_id": fixture.workspace_id},
            )
            connection.execute(
                text(
                    """
                    insert into roles (id, workspace_id, slug, display_name, status)
                    values (:id, :workspace_id, 'upgrade-reader', 'Upgrade Reader', 'active')
                    """
                ),
                {"id": fixture.role_id, "workspace_id": fixture.workspace_id},
            )
            connection.execute(
                text(
                    """
                    insert into role_permissions (role_id, permission_code)
                    values (:role_id, 'capability.describe'),
                           (:role_id, 'capability.invoke.read_only')
                    """
                ),
                {"role_id": fixture.role_id},
            )
            connection.execute(
                text(
                    """
                    insert into capabilities
                        (id, workspace_id, application_instance_id, name, version, provider_type,
                         adapter, operation, auth_mode, risk_class, input_schema, output_schema,
                         status)
                    values
                        (:id, :workspace_id, :application_id, 'Upgrade Phonebook', 1, 'mock',
                         'mock', 'phonebook.search', 'user', 'read_only',
                         cast(:input_schema as jsonb), cast(:output_schema as jsonb), 'active')
                    """
                ),
                {
                    "id": fixture.capability_id,
                    "workspace_id": fixture.workspace_id,
                    "application_id": fixture.application_id,
                    "input_schema": json.dumps({"type": "object"}),
                    "output_schema": json.dumps({"type": "object"}),
                },
            )
            connection.execute(
                text(
                    """
                    insert into bindings
                        (id, workspace_id, agent_id, user_id, capability_id, role_id, status)
                    values
                        (:id, :workspace_id, :agent_id, :user_id, :capability_id, :role_id,
                         'active')
                    """
                ),
                {
                    "id": fixture.binding_id,
                    "workspace_id": fixture.workspace_id,
                    "agent_id": fixture.agent_id,
                    "user_id": fixture.user_id,
                    "capability_id": fixture.capability_id,
                    "role_id": fixture.role_id,
                },
            )
            connection.execute(
                text(
                    """
                    insert into audit_events
                        (id, request_id, workspace_id, agent_id, user_id, capability_id,
                         application_instance_id, decision, outcome, error_code, latency_ms,
                         remote_addr, actor_type)
                    values
                        (:id, 'req_upgrade_fixture', :workspace_id, :agent_id, :user_id,
                         :capability_id, :application_id, 'allow', 'success', null, 12,
                         '127.0.0.1', 'agent')
                    """
                ),
                {
                    "id": fixture.audit_id,
                    "workspace_id": fixture.workspace_id,
                    "agent_id": fixture.agent_id,
                    "user_id": fixture.user_id,
                    "capability_id": fixture.capability_id,
                    "application_id": fixture.application_id,
                },
            )
            connection.execute(
                text(
                    """
                    insert into usage_events
                        (id, workspace_id, agent_id, user_id, capability_id,
                         application_instance_id, units, status, latency_ms)
                    values
                        (:id, :workspace_id, :agent_id, :user_id, :capability_id,
                         :application_id, 1, 'success', 12)
                    """
                ),
                {
                    "id": fixture.usage_id,
                    "workspace_id": fixture.workspace_id,
                    "agent_id": fixture.agent_id,
                    "user_id": fixture.user_id,
                    "capability_id": fixture.capability_id,
                    "application_id": fixture.application_id,
                },
            )
    finally:
        engine.dispose()


class WorkflowClientForTestClient:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def get(
        self,
        path: str,
        *,
        token: str | None = None,
        query: dict[str, object | None] | None = None,
    ) -> JSONDict:
        response = self.client.get(path, headers=self._headers(token), params=self._query(query))
        assert response.status_code == 200, response.text
        return response.json()

    def post(
        self,
        path: str,
        *,
        token: str | None = None,
        payload: JSONDict | None = None,
    ) -> JSONDict:
        response = self.client.post(path, headers=self._headers(token), json=payload or {})
        assert 200 <= response.status_code < 300, response.text
        return response.json()

    @staticmethod
    def _headers(token: str | None) -> dict[str, str]:
        if token is None:
            return {}
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _query(query: dict[str, object | None] | None) -> dict[str, object]:
        return {key: value for key, value in (query or {}).items() if value is not None}


def settings_for_database(database_url: str) -> Settings:
    pepper = "integration-token-pepper"
    return Settings(
        database_url=database_url,
        environment="integration",
        agent_token_pepper=pepper,
        admin_bootstrap_token_hash=hash_token("admin-token", pepper),
        secret_encryption_key=SecretCipher.generate_key(),
    )
