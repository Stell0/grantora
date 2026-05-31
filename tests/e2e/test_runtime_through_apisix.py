from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from grantora.cli.demo_workflow import DemoSeedConfig, DemoSeedResult, HTTPGrantoraClient, seed_demo

pytestmark = pytest.mark.e2e


@dataclass(frozen=True)
class E2ESettings:
    api_url: str
    runtime_url: str
    admin_token: str
    timeout_seconds: float


@dataclass(frozen=True)
class E2EContext:
    settings: E2ESettings
    seed_config: DemoSeedConfig
    seed: DemoSeedResult
    admin: httpx.Client
    runtime: httpx.Client


@pytest.fixture()
def e2e_context(tmp_path: Path) -> E2EContext:
    settings = required_e2e_settings()
    run_id = uuid4().hex[:8]
    seed_config = DemoSeedConfig(
        api_url=settings.api_url,
        admin_token=settings.admin_token,
        output_env_path=tmp_path / "demo.env",
        timeout_seconds=settings.timeout_seconds,
        workspace_slug=f"e2e-{run_id}",
        application_slug=f"mock-phonebook-{run_id}",
        user_external_id=f"alice-{run_id}",
        capability_id=f"mock.phonebook.search.{run_id}",
        role_slug=f"phonebook-reader-{run_id}",
        agent_slug=f"hermes-e2e-{run_id}",
    )
    workflow_client = HTTPGrantoraClient(
        settings.api_url,
        timeout_seconds=settings.timeout_seconds,
    )
    seed = seed_demo(workflow_client, seed_config)
    assert seed.agent_token is not None
    sync_response = workflow_client.post("/v1/admin/apisix/sync", token=settings.admin_token)
    assert sync_response["status"] == "ok"

    with httpx.Client(
        base_url=settings.api_url,
        timeout=settings.timeout_seconds,
        trust_env=False,
    ) as admin:
        with httpx.Client(
            base_url=settings.runtime_url,
            timeout=settings.timeout_seconds,
            trust_env=False,
        ) as runtime:
            yield E2EContext(settings, seed_config, seed, admin, runtime)


def test_agent_discovers_and_invokes_allowed_capability_through_apisix(
    e2e_context: E2EContext,
) -> None:
    me_response = e2e_context.runtime.get("/v1/me", headers=agent_headers(e2e_context))
    discovery_response = e2e_context.runtime.get(
        "/v1/capabilities",
        headers=agent_headers(e2e_context),
        params={"user": e2e_context.seed_config.user_external_id},
    )
    invocation_response, started_at = invoke_runtime(
        e2e_context,
        e2e_context.seed.capability_id,
        e2e_context.seed_config.user_external_id,
        request_id="req_e2e_success",
    )

    assert me_response.status_code == 200
    assert discovery_response.status_code == 200
    assert e2e_context.seed.capability_id in [
        capability["id"] for capability in discovery_response.json()["capabilities"]
    ]
    assert invocation_response.status_code == 200
    assert invocation_response.json()["data"] == {"contacts": []}
    assert_invocation_recorded(
        e2e_context,
        request_id="req_e2e_success",
        capability_id=e2e_context.seed.capability_id,
        start_time=started_at,
        usage_status="success",
        error_code=None,
    )


def test_denied_and_adapter_error_attempts_are_audited_and_counted(
    e2e_context: E2EContext,
) -> None:
    bob = admin_post(
        e2e_context,
        "/v1/admin/users",
        {
            "workspace_id": e2e_context.seed.workspace_id,
            "external_id": f"bob-{uuid4().hex[:8]}",
            "display_name": "Bob",
        },
    )["user"]

    no_binding_response, no_binding_started_at = invoke_runtime(
        e2e_context,
        e2e_context.seed.capability_id,
        bob["external_id"],
        request_id="req_e2e_no_binding",
    )
    missing_user_response, missing_user_started_at = invoke_runtime(
        e2e_context,
        e2e_context.seed.capability_id,
        f"missing-{uuid4().hex[:8]}",
        request_id="req_e2e_wrong_user",
    )

    admin_patch(
        e2e_context,
        f"/v1/admin/capabilities/{e2e_context.seed.capability_id}",
        {"status": "disabled"},
    )
    disabled_response, disabled_started_at = invoke_runtime(
        e2e_context,
        e2e_context.seed.capability_id,
        e2e_context.seed_config.user_external_id,
        request_id="req_e2e_disabled_capability",
    )
    admin_patch(
        e2e_context,
        f"/v1/admin/capabilities/{e2e_context.seed.capability_id}",
        {"status": "active"},
    )

    admin_patch(
        e2e_context,
        f"/v1/admin/secrets/{e2e_context.seed.secret_id}",
        {"status": "revoked"},
    )
    missing_secret_response, missing_secret_started_at = invoke_runtime(
        e2e_context,
        e2e_context.seed.capability_id,
        e2e_context.seed_config.user_external_id,
        request_id="req_e2e_missing_secret",
    )

    upstream_error_capability = create_nethvoice_upstream_error_capability(e2e_context)
    upstream_error_response, upstream_error_started_at = invoke_runtime(
        e2e_context,
        upstream_error_capability,
        e2e_context.seed_config.user_external_id,
        request_id="req_e2e_upstream_error",
    )

    assert_error_response(no_binding_response, 403, "capability_denied")
    assert_error_response(missing_user_response, 403, "capability_denied")
    assert_error_response(disabled_response, 403, "capability_denied")
    assert_error_response(missing_secret_response, 424, "secret_not_found")
    assert_error_response(upstream_error_response, 502, "upstream_error")

    for request_id, start_time, usage_status, error_code, capability_id in [
        (
            "req_e2e_no_binding",
            no_binding_started_at,
            "denied",
            "capability_denied",
            e2e_context.seed.capability_id,
        ),
        (
            "req_e2e_wrong_user",
            missing_user_started_at,
            "denied",
            "capability_denied",
            e2e_context.seed.capability_id,
        ),
        (
            "req_e2e_disabled_capability",
            disabled_started_at,
            "denied",
            "capability_denied",
            e2e_context.seed.capability_id,
        ),
        (
            "req_e2e_missing_secret",
            missing_secret_started_at,
            "denied",
            "secret_not_found",
            e2e_context.seed.capability_id,
        ),
        (
            "req_e2e_upstream_error",
            upstream_error_started_at,
            "error",
            "upstream_error",
            upstream_error_capability,
        ),
    ]:
        assert_invocation_recorded(
            e2e_context,
            request_id=request_id,
            capability_id=capability_id,
            start_time=start_time,
            usage_status=usage_status,
            error_code=error_code,
        )


def create_nethvoice_upstream_error_capability(e2e_context: E2EContext) -> str:
    run_id = uuid4().hex[:8]
    application = admin_post(
        e2e_context,
        "/v1/admin/applications",
        {
            "workspace_id": e2e_context.seed.workspace_id,
            "slug": f"nethvoice-error-{run_id}",
            "display_name": "NethVoice Error Fixture",
            "provider_type": "nethvoice",
            "base_url": "http://127.0.0.1:9",
        },
    )["application"]
    capability_id = f"nethvoice.phonebook.error.{run_id}"
    admin_post(
        e2e_context,
        "/v1/admin/capabilities",
        {
            "id": capability_id,
            "workspace_id": e2e_context.seed.workspace_id,
            "application_instance_id": application["id"],
            "name": "NethVoice upstream error",
            "version": 1,
            "provider_type": "nethvoice",
            "adapter": "nethvoice",
            "operation": "phonebook.search",
            "auth_mode": "user",
            "risk_class": "read_only",
            "input_schema": phonebook_input_schema(),
            "output_schema": nethvoice_output_schema(),
        },
    )
    admin_post(
        e2e_context,
        "/v1/admin/bindings",
        {
            "workspace_id": e2e_context.seed.workspace_id,
            "agent_id": e2e_context.seed.agent_id,
            "user_id": e2e_context.seed.user_id,
            "capability_id": capability_id,
            "role_id": e2e_context.seed.role_id,
        },
    )
    admin_post(
        e2e_context,
        "/v1/admin/secrets",
        {
            "workspace_id": e2e_context.seed.workspace_id,
            "application_instance_id": application["id"],
            "owner_type": "user",
            "owner_id": e2e_context.seed.user_id,
            "secret_type": "bearer_token",
            "value": "e2e-upstream-token",
        },
    )
    return capability_id


def invoke_runtime(
    e2e_context: E2EContext,
    capability_id: str,
    user: str,
    *,
    request_id: str,
) -> tuple[httpx.Response, str]:
    started_at = datetime.now(UTC).isoformat()
    response = e2e_context.runtime.post(
        f"/v1/invoke/{capability_id}",
        headers=agent_headers(e2e_context, request_id=request_id),
        json={"user": user, "input": {"query": "Mario", "limit": 5}},
    )
    return response, started_at


def assert_invocation_recorded(
    e2e_context: E2EContext,
    *,
    request_id: str,
    capability_id: str,
    start_time: str,
    usage_status: str,
    error_code: str | None,
) -> None:
    audit_response = admin_get(
        e2e_context,
        "/v1/admin/audit",
        params={
            "workspace_id": e2e_context.seed.workspace_id,
            "capability_id": capability_id,
            "actor_type": "agent",
            "start_time": start_time,
            "limit": 500,
        },
    )
    usage_response = admin_get(
        e2e_context,
        "/v1/admin/usage",
        params={
            "workspace_id": e2e_context.seed.workspace_id,
            "capability_id": capability_id,
            "status": usage_status,
            "start_time": start_time,
            "limit": 500,
        },
    )
    audit_event = next(
        event for event in audit_response["audit"] if event["request_id"] == request_id
    )

    assert audit_event["error_code"] == error_code
    assert any(event["status"] == usage_status for event in usage_response["usage"])


def assert_error_response(response: httpx.Response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == code
    assert "Authorization" not in response.text


def admin_get(
    e2e_context: E2EContext,
    path: str,
    *,
    params: dict[str, object] | None = None,
) -> dict[str, object]:
    response = e2e_context.admin.get(path, headers=admin_headers(e2e_context), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def admin_post(e2e_context: E2EContext, path: str, payload: dict[str, object]) -> dict[str, object]:
    response = e2e_context.admin.post(path, headers=admin_headers(e2e_context), json=payload)
    assert 200 <= response.status_code < 300, response.text
    return response.json()


def admin_patch(
    e2e_context: E2EContext,
    path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    response = e2e_context.admin.patch(path, headers=admin_headers(e2e_context), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def admin_headers(e2e_context: E2EContext) -> dict[str, str]:
    return {"Authorization": f"Bearer {e2e_context.settings.admin_token}"}


def agent_headers(e2e_context: E2EContext, *, request_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {e2e_context.seed.agent_token}"}
    if request_id is not None:
        headers["X-Request-Id"] = request_id
    return headers


def phonebook_input_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def nethvoice_output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "contacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "display_name": {"type": "string"},
                        "phone": {"type": "string"},
                        "company": {"type": "string"},
                        "source": {"type": "string", "const": "nethvoice"},
                    },
                    "required": ["display_name", "phone", "company", "source"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["contacts"],
        "additionalProperties": False,
    }


def required_e2e_settings() -> E2ESettings:
    if os.environ.get("GRANTORA_RUN_E2E") != "1":
        pytest.skip("Set GRANTORA_RUN_E2E=1 with a running compose stack to run e2e tests.")
    admin_token = os.environ.get("ADMIN_BOOTSTRAP_TOKEN")
    if not admin_token:
        pytest.skip("Set ADMIN_BOOTSTRAP_TOKEN to run e2e tests.")
    return E2ESettings(
        api_url=os.environ.get("GRANTORA_E2E_API_URL")
        or os.environ.get("GRANTORA_API_URL", "http://localhost:8080"),
        runtime_url=os.environ.get("GRANTORA_E2E_RUNTIME_URL")
        or os.environ.get("GRANTORA_RUNTIME_URL", "http://localhost:9080"),
        admin_token=admin_token,
        timeout_seconds=float(os.environ.get("GRANTORA_E2E_TIMEOUT_SECONDS", "15")),
    )
