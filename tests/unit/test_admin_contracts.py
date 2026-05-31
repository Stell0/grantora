from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import BaseModel

from grantora.auth import hash_token
from grantora.config import Settings
from grantora.db import Base, Database
from grantora.main import create_app
from grantora.schemas import (
    AdminAgentCreateResponse,
    AdminAgentListResponse,
    AdminAgentResponse,
    AdminApisixStatusResponse,
    AdminApisixSyncResponse,
    AdminApplicationListResponse,
    AdminApplicationResponse,
    AdminAuditListResponse,
    AdminBindingListResponse,
    AdminBindingResponse,
    AdminCapabilityListResponse,
    AdminCapabilityResponse,
    AdminCapabilityTemplateListResponse,
    AdminPermissionListResponse,
    AdminPermissionResponse,
    AdminRoleListResponse,
    AdminRoleResponse,
    AdminSecretListResponse,
    AdminSecretResponse,
    AdminSecretRotationResponse,
    AdminUsageListResponse,
    AdminUserListResponse,
    AdminUserResponse,
    AdminWorkspaceListResponse,
    AdminWorkspaceResponse,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

ADMIN_RESPONSE_MODELS: tuple[type[BaseModel], ...] = (
    AdminAgentCreateResponse,
    AdminAgentListResponse,
    AdminAgentResponse,
    AdminApisixStatusResponse,
    AdminApisixSyncResponse,
    AdminApplicationListResponse,
    AdminApplicationResponse,
    AdminAuditListResponse,
    AdminBindingListResponse,
    AdminBindingResponse,
    AdminCapabilityTemplateListResponse,
    AdminCapabilityListResponse,
    AdminCapabilityResponse,
    AdminPermissionListResponse,
    AdminPermissionResponse,
    AdminRoleListResponse,
    AdminRoleResponse,
    AdminSecretListResponse,
    AdminSecretResponse,
    AdminSecretRotationResponse,
    AdminUsageListResponse,
    AdminUserListResponse,
    AdminUserResponse,
    AdminWorkspaceListResponse,
    AdminWorkspaceResponse,
)


def test_admin_response_models_match_contract_fixture() -> None:
    actual = {
        model.__name__: sorted(model.model_fields)
        for model in sorted(ADMIN_RESPONSE_MODELS, key=lambda item: item.__name__)
    }

    assert actual == load_contract_fixture()["response_models"]


def test_admin_error_response_shape_matches_contract_fixture(tmp_path: Path) -> None:
    pepper = "contract-token-pepper"
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'grantora.sqlite'}",
        environment="test",
        agent_token_pepper=pepper,
        admin_bootstrap_token_hash=hash_token("admin-token", pepper),
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    app = create_app(settings=settings, database=database)

    with TestClient(app) as client:
        response = client.get(
            "/v1/admin/workspaces",
            headers={"Authorization": "Bearer wrong-token", "X-Request-Id": "req_contract"},
        )

    body = response.json()
    actual = {
        "body_keys": sorted(body),
        "error_keys": sorted(body["error"]),
        "status": body["status"],
    }

    assert response.status_code == 401
    assert body["request_id"] == "req_contract"
    assert actual == load_contract_fixture()["standard_error_response"]


def load_contract_fixture() -> dict[str, object]:
    return json.loads((FIXTURES_DIR / "admin_contract_models.json").read_text(encoding="utf-8"))
