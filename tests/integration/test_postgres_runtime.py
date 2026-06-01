from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from grantora.auth import hash_token
from grantora.cli.demo_workflow import DemoSeedConfig, JSONDict, seed_demo
from grantora.config import Settings
from grantora.db import Database
from grantora.db.models import Workspace
from grantora.main import create_app
from grantora.secrets import SecretCipher

from .conftest import IsolatedPostgresSchema, table_names_for_schema

pytestmark = pytest.mark.integration


def test_metadata_create_all_and_postgres_session_lifecycle(
    current_postgres_schema: IsolatedPostgresSchema,
) -> None:
    table_names = table_names_for_schema(current_postgres_schema)
    assert {"workspaces", "agents", "usage_events"} <= table_names

    database = Database(settings_for_database(current_postgres_schema.database_url))
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


def test_admin_api_bootstrap_and_runtime_invocation_use_postgres_records(
    current_postgres_schema: IsolatedPostgresSchema,
    tmp_path: Path,
) -> None:
    settings = settings_for_database(current_postgres_schema.database_url)
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
