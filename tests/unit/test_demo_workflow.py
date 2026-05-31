from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from grantora.cli.demo_workflow import (
    DemoSeedConfig,
    SmokeConfig,
    WorkflowError,
    run_smoke,
    seed_demo,
    write_demo_env,
)


class FakeGrantoraAPI:
    def __init__(self) -> None:
        self.agent_token = "grt_agent_demo"
        self.workspaces: list[dict[str, Any]] = []
        self.applications: list[dict[str, Any]] = []
        self.users: list[dict[str, Any]] = []
        self.capabilities: list[dict[str, Any]] = []
        self.roles: list[dict[str, Any]] = []
        self.agents: list[dict[str, Any]] = []
        self.bindings: list[dict[str, Any]] = []
        self.secrets: list[dict[str, Any]] = []
        self.permissions = [
            {"code": "capability.describe", "description": "Describe capabilities"},
            {
                "code": "capability.invoke.read_only",
                "description": "Invoke read-only capabilities",
            },
        ]

    def get(
        self,
        path: str,
        *,
        token: str | None = None,
        query: dict[str, object | None] | None = None,
    ) -> dict[str, Any]:
        query = query or {}
        if path == "/healthz":
            return {"status": "ok", "service": "grantora-api"}
        if path == "/readyz":
            return {"status": "ok", "checks": {"database": "ok"}}
        if path == "/v1/admin/workspaces":
            return {"workspaces": self._active(self.workspaces, query), "limit": 500, "offset": 0}
        if path == "/v1/admin/applications":
            items = self._filter(self.applications, query, ["workspace_id"])
            return {"applications": self._active(items, query), "limit": 500, "offset": 0}
        if path == "/v1/admin/users":
            items = self._filter(self.users, query, ["workspace_id"])
            return {"users": self._active(items, query), "limit": 500, "offset": 0}
        if path == "/v1/admin/capabilities":
            items = self._filter(self.capabilities, query, ["workspace_id"])
            return {"capabilities": self._active(items, query), "limit": 500, "offset": 0}
        if path == "/v1/admin/permissions":
            return {"permissions": self.permissions, "limit": 500, "offset": 0}
        if path == "/v1/admin/roles":
            items = self._filter(self.roles, query, ["workspace_id"])
            return {"roles": self._active(items, query), "limit": 500, "offset": 0}
        if path == "/v1/admin/agents":
            items = self._filter(self.agents, query, ["workspace_id"])
            return {"agents": self._active(items, query), "limit": 500, "offset": 0}
        if path == "/v1/admin/bindings":
            fields = ["workspace_id", "agent_id", "user_id", "capability_id", "role_id"]
            items = self._filter(self.bindings, query, fields)
            return {"bindings": self._active(items, query), "limit": 500, "offset": 0}
        if path == "/v1/admin/secrets":
            fields = ["workspace_id", "application_instance_id", "owner_type", "owner_id"]
            items = self._filter(self.secrets, query, fields)
            return {"secrets": self._active(items, query), "limit": 500, "offset": 0}
        if path == "/v1/capabilities" and token == self.agent_token:
            capabilities = self.capabilities if query.get("user") == "alice" else []
            return {"capabilities": capabilities, "limit": 100, "offset": 0}
        if path == "/v1/mcp/tools" and token == self.agent_token:
            tools = []
            if query.get("user") == "alice":
                tools = [
                    {
                        "name": "mock_phonebook_search",
                        "description": "Search phonebook",
                        "inputSchema": {},
                        "_meta": {
                            "grantora/capability_id": "mock.phonebook.search",
                            "grantora/invocation_path": "/v1/invoke/mock.phonebook.search",
                        },
                    }
                ]
            return {"tools": tools}
        raise AssertionError(f"unexpected GET {path}")

    def post(
        self,
        path: str,
        *,
        token: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        if path == "/v1/admin/workspaces":
            workspace = {"id": self._id(), "status": "active", **payload}
            self.workspaces.append(workspace)
            return {"workspace": workspace}
        if path == "/v1/admin/applications":
            application = {"id": self._id(), "status": "active", **payload}
            self.applications.append(application)
            return {"application": application}
        if path == "/v1/admin/users":
            user = {"id": self._id(), "status": "active", **payload}
            self.users.append(user)
            return {"user": user}
        if path == "/v1/admin/capabilities":
            capability = {"status": "active", **payload}
            self.capabilities.append(capability)
            return {"capability": capability}
        if path == "/v1/admin/roles":
            role = {"id": self._id(), "status": "active", **payload}
            self.roles.append(role)
            return {"role": role}
        if path == "/v1/admin/agents":
            agent = {"id": self._id(), "status": "active", **payload}
            self.agents.append(agent)
            return {"agent": agent, "token": self.agent_token}
        if path == "/v1/admin/bindings":
            binding = {"id": self._id(), "status": "active", **payload}
            self.bindings.append(binding)
            return {"binding": binding}
        if path == "/v1/admin/secrets":
            secret = {
                "id": self._id(),
                "status": "active",
                "workspace_id": payload["workspace_id"],
                "application_instance_id": payload["application_instance_id"],
                "owner_type": payload["owner_type"],
                "owner_id": payload["owner_id"],
                "secret_type": payload["secret_type"],
            }
            self.secrets.append(secret)
            return {"secret": secret}
        if path == "/v1/admin/apisix/sync":
            return {"status": "ok", "checked_routes": 1, "changed_routes": 0}
        if path == "/v1/invoke/mock.phonebook.search" and token == self.agent_token:
            return {"status": "ok", "capability": "mock.phonebook.search", "data": {"contacts": []}}
        if path == "/v1/mcp/call" and token == self.agent_token:
            assert payload == {
                "user": "alice",
                "name": "mock_phonebook_search",
                "arguments": {"query": "Mario", "limit": 5},
            }
            return {
                "content": [{"type": "text", "text": '{"contacts":[]}'}],
                "structuredContent": {"contacts": []},
                "isError": False,
                "_meta": {"grantora/capability_id": "mock.phonebook.search"},
            }
        raise AssertionError(f"unexpected POST {path}")

    @staticmethod
    def _filter(
        items: list[dict[str, Any]],
        query: dict[str, object | None],
        fields: list[str],
    ) -> list[dict[str, Any]]:
        selected = items
        for field in fields:
            if query.get(field) is not None:
                selected = [item for item in selected if item[field] == query[field]]
        return selected

    @staticmethod
    def _active(
        items: list[dict[str, Any]],
        query: dict[str, object | None],
    ) -> list[dict[str, Any]]:
        if query.get("include_disabled") is True or query.get("include_revoked") is True:
            return items
        return [item for item in items if item["status"] == "active"]

    @staticmethod
    def _id() -> str:
        return str(uuid4())


def test_demo_seed_creates_then_reuses_public_api_resources(tmp_path) -> None:
    api = FakeGrantoraAPI()
    config = DemoSeedConfig(
        api_url="http://api.test",
        admin_token="admin-token",
        output_env_path=tmp_path / "demo.env",
    )

    first_result = seed_demo(api, config)
    write_demo_env(config.output_env_path, first_result, config)
    second_result = seed_demo(api, replace(config, existing_agent_token=first_result.agent_token))

    assert {report.action for report in first_result.reports} == {"created", "reused"}
    assert [report.action for report in second_result.reports] == ["reused"] * len(
        second_result.reports
    )
    assert first_result.agent_token == "grt_agent_demo"
    assert second_result.agent_token == "grt_agent_demo"
    assert len(api.workspaces) == 1
    assert len(api.agents) == 1
    demo_env = config.output_env_path.read_text(encoding="utf-8")
    assert "DEMO_AGENT_TOKEN=grt_agent_demo" in demo_env
    assert "demo-upstream-token" not in demo_env


def test_smoke_checks_health_sync_discovery_and_invocation(tmp_path) -> None:
    api = FakeGrantoraAPI()
    seed_config = DemoSeedConfig(
        api_url="http://api.test",
        admin_token="admin-token",
        output_env_path=tmp_path / "demo.env",
    )
    seed_result = seed_demo(api, seed_config)
    assert seed_result.agent_token is not None

    checks = run_smoke(
        api,
        api,
        SmokeConfig(
            api_url="http://api.test",
            runtime_url="http://runtime.test",
            admin_token="admin-token",
            agent_token=seed_result.agent_token,
        ),
    )

    assert [check.name for check in checks] == [
        "healthz",
        "readyz",
        "apisix-sync",
        "runtime-discovery",
        "mock-invocation",
        "mcp-tool-discovery",
        "mcp-tool-call",
    ]


def test_smoke_fails_when_discovery_omits_demo_capability() -> None:
    api = FakeGrantoraAPI()

    with pytest.raises(WorkflowError, match="did not include required capability"):
        run_smoke(
            api,
            api,
            SmokeConfig(
                api_url="http://api.test",
                runtime_url="http://runtime.test",
                admin_token="admin-token",
                agent_token=api.agent_token,
                capability_id="missing.capability",
            ),
        )
