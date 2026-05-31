from __future__ import annotations

import json
import os
import shlex
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from grantora.openapi.tools import capability_tool_name

JSONDict = dict[str, Any]
Action = Literal["created", "reused"]

ACTIVE_STATUS = "active"
DEFAULT_API_URL = "http://localhost:8080"
DEFAULT_RUNTIME_URL = "http://localhost:9080"
DEFAULT_DEMO_ENV_PATH = ".grantora-demo.env"
DEFAULT_ROLE_PERMISSIONS = (
    "capability.describe",
    "capability.invoke.read_only",
)


class WorkflowError(RuntimeError):
    """Raised when a human workflow cannot complete safely."""


class GrantoraClient(Protocol):
    def get(
        self,
        path: str,
        *,
        token: str | None = None,
        query: dict[str, object | None] | None = None,
    ) -> JSONDict: ...

    def post(
        self,
        path: str,
        *,
        token: str | None = None,
        payload: JSONDict | None = None,
    ) -> JSONDict: ...


class HTTPGrantoraClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get(
        self,
        path: str,
        *,
        token: str | None = None,
        query: dict[str, object | None] | None = None,
    ) -> JSONDict:
        return self._request("GET", path, token=token, query=query)

    def post(
        self,
        path: str,
        *,
        token: str | None = None,
        payload: JSONDict | None = None,
    ) -> JSONDict:
        return self._request("POST", path, token=token, payload=payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        query: dict[str, object | None] | None = None,
        payload: JSONDict | None = None,
    ) -> JSONDict:
        url = _build_url(self.base_url, path, query)
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return _decode_json_response(response.read())
        except urllib.error.HTTPError as exc:
            raise WorkflowError(_safe_http_error_message(method, path, exc)) from exc
        except urllib.error.URLError as exc:
            raise WorkflowError(f"{method} {path} failed: {exc.reason}") from exc


@dataclass(frozen=True)
class ResourceReport:
    name: str
    label: str
    action: Action
    identifier: str


@dataclass(frozen=True)
class CheckReport:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DemoSeedConfig:
    api_url: str
    admin_token: str
    output_env_path: Path
    existing_agent_token: str | None = None
    timeout_seconds: float = 10.0
    workspace_slug: str = "demo"
    workspace_display_name: str = "Grantora Demo"
    application_slug: str = "mock-phonebook"
    application_display_name: str = "Mock Phonebook"
    application_provider_type: str = "mock"
    application_base_url: str = "https://mock.example.test"
    user_external_id: str = "alice"
    user_display_name: str = "Alice"
    capability_id: str = "mock.phonebook.search"
    capability_name: str = "Search phonebook"
    role_slug: str = "phonebook-reader"
    role_display_name: str = "Phonebook Reader"
    agent_slug: str = "hermes-demo"
    agent_display_name: str = "Hermes Demo"
    secret_type: str = "bearer_token"
    upstream_secret: str = "demo-upstream-token"
    role_permission_codes: tuple[str, ...] = DEFAULT_ROLE_PERMISSIONS


@dataclass(frozen=True)
class DemoSeedResult:
    reports: list[ResourceReport]
    workspace_id: str
    application_id: str
    user_id: str
    capability_id: str
    role_id: str
    agent_id: str
    binding_id: str
    secret_id: str
    agent_token: str | None


@dataclass(frozen=True)
class SmokeConfig:
    api_url: str
    runtime_url: str
    admin_token: str
    agent_token: str
    user_external_id: str = "alice"
    capability_id: str = "mock.phonebook.search"
    timeout_seconds: float = 10.0
    invocation_input: JSONDict | None = None


def demo_seed_config_from_env() -> DemoSeedConfig:
    return DemoSeedConfig(
        api_url=_env("GRANTORA_API_URL", DEFAULT_API_URL),
        admin_token=_required_env("ADMIN_BOOTSTRAP_TOKEN"),
        output_env_path=Path(_env("DEMO_OUTPUT_ENV", DEFAULT_DEMO_ENV_PATH)),
        existing_agent_token=os.environ.get("DEMO_AGENT_TOKEN"),
        timeout_seconds=_float_env("GRANTORA_WORKFLOW_TIMEOUT_SECONDS", 10.0),
        workspace_slug=_env("DEMO_WORKSPACE_SLUG", "demo"),
        workspace_display_name=_env("DEMO_WORKSPACE_NAME", "Grantora Demo"),
        application_slug=_env("DEMO_APPLICATION_SLUG", "mock-phonebook"),
        application_display_name=_env("DEMO_APPLICATION_NAME", "Mock Phonebook"),
        user_external_id=_env("DEMO_USER_EXTERNAL_ID", "alice"),
        user_display_name=_env("DEMO_USER_NAME", "Alice"),
        capability_id=_env("DEMO_CAPABILITY_ID", "mock.phonebook.search"),
        capability_name=_env("DEMO_CAPABILITY_NAME", "Search phonebook"),
        role_slug=_env("DEMO_ROLE_SLUG", "phonebook-reader"),
        role_display_name=_env("DEMO_ROLE_NAME", "Phonebook Reader"),
        agent_slug=_env("DEMO_AGENT_SLUG", "hermes-demo"),
        agent_display_name=_env("DEMO_AGENT_NAME", "Hermes Demo"),
        upstream_secret=_env("DEMO_UPSTREAM_SECRET", "demo-upstream-token"),
    )


def smoke_config_from_env() -> SmokeConfig:
    return SmokeConfig(
        api_url=_env("GRANTORA_API_URL", DEFAULT_API_URL),
        runtime_url=_env(
            "GRANTORA_RUNTIME_URL",
            _env("GRANTORA_PUBLIC_BASE_URL", _env("APISIX_PUBLIC_URL", DEFAULT_RUNTIME_URL)),
        ),
        admin_token=_required_env("ADMIN_BOOTSTRAP_TOKEN"),
        agent_token=_required_env("DEMO_AGENT_TOKEN"),
        user_external_id=_env("DEMO_USER_EXTERNAL_ID", "alice"),
        capability_id=_env("DEMO_CAPABILITY_ID", "mock.phonebook.search"),
        timeout_seconds=_float_env("GRANTORA_WORKFLOW_TIMEOUT_SECONDS", 10.0),
        invocation_input={
            "query": _env("DEMO_QUERY", "Mario"),
            "limit": _int_env("DEMO_LIMIT", 5),
        },
    )


def seed_demo(client: GrantoraClient, config: DemoSeedConfig) -> DemoSeedResult:
    reports: list[ResourceReport] = []

    workspace, action = _ensure_workspace(client, config)
    reports.append(_report("workspace", workspace["slug"], action, workspace["id"]))

    application, action = _ensure_application(client, config, workspace["id"])
    reports.append(_report("application", application["slug"], action, application["id"]))

    user, action = _ensure_user(client, config, workspace["id"])
    reports.append(_report("user", user["external_id"], action, user["id"]))

    capability, action = _ensure_capability(client, config, workspace["id"], application["id"])
    reports.append(_report("capability", capability["id"], action, capability["id"]))

    _ensure_permissions(client, config)
    reports.append(_report("permissions", "default runtime permissions", "reused", "built-in"))

    role, action = _ensure_role(client, config, workspace["id"])
    reports.append(_report("role", role["slug"], action, role["id"]))

    agent, agent_token, action = _ensure_agent(client, config, workspace["id"])
    reports.append(_report("agent", agent["slug"], action, agent["id"]))

    binding, action = _ensure_binding(
        client,
        config,
        workspace_id=workspace["id"],
        agent_id=agent["id"],
        user_id=user["id"],
        role_id=role["id"],
    )
    reports.append(_report("binding", config.capability_id, action, binding["id"]))

    secret, action = _ensure_secret(
        client,
        config,
        workspace_id=workspace["id"],
        application_id=application["id"],
        user_id=user["id"],
    )
    reports.append(
        _report("secret", f"{config.user_external_id} upstream secret", action, secret["id"])
    )

    return DemoSeedResult(
        reports=reports,
        workspace_id=workspace["id"],
        application_id=application["id"],
        user_id=user["id"],
        capability_id=capability["id"],
        role_id=role["id"],
        agent_id=agent["id"],
        binding_id=binding["id"],
        secret_id=secret["id"],
        agent_token=agent_token,
    )


def run_smoke(
    admin_client: GrantoraClient,
    runtime_client: GrantoraClient,
    config: SmokeConfig,
) -> list[CheckReport]:
    checks = [
        _check_health(admin_client),
        _check_ready(admin_client),
        _check_apisix_sync(admin_client, config),
        _check_discovery(runtime_client, config),
        _check_invocation(runtime_client, config),
        _check_filtered_openapi(runtime_client, config),
        _check_mcp_tools(runtime_client, config),
        _check_mcp_call(runtime_client, config),
    ]
    return checks


def write_demo_env(path: Path, result: DemoSeedResult, config: DemoSeedConfig) -> None:
    values = {
        "DEMO_WORKSPACE_ID": result.workspace_id,
        "DEMO_APPLICATION_ID": result.application_id,
        "DEMO_USER_ID": result.user_id,
        "DEMO_USER_EXTERNAL_ID": config.user_external_id,
        "DEMO_CAPABILITY_ID": result.capability_id,
        "DEMO_ROLE_ID": result.role_id,
        "DEMO_AGENT_ID": result.agent_id,
        "DEMO_BINDING_ID": result.binding_id,
        "DEMO_SECRET_ID": result.secret_id,
    }
    if result.agent_token is not None:
        values["DEMO_AGENT_TOKEN"] = result.agent_token

    content = ["# Generated by make demo-seed. Keep this file out of source control."]
    content.extend(f"{key}={shlex.quote(value)}" for key, value in values.items())
    path.write_text("\n".join(content) + "\n", encoding="utf-8")
    path.chmod(0o600)


def print_seed_result(result: DemoSeedResult, config: DemoSeedConfig) -> None:
    print(f"Demo seed completed against {config.api_url}")
    for report in result.reports:
        print(f"{report.action:7} {report.name:12} {report.label} ({report.identifier})")
    print(f"Wrote demo metadata to {config.output_env_path}")
    if result.agent_token is None:
        print("Existing agents do not return plaintext tokens; set DEMO_AGENT_TOKEN for smoke.")


def print_smoke_result(checks: list[CheckReport], config: SmokeConfig) -> None:
    print(f"Smoke completed against API {config.api_url} and runtime {config.runtime_url}")
    for check in checks:
        print(f"ok {check.name}: {check.detail}")


def _ensure_workspace(client: GrantoraClient, config: DemoSeedConfig) -> tuple[JSONDict, Action]:
    response = client.get(
        "/v1/admin/workspaces",
        token=config.admin_token,
        query={"include_disabled": True, "limit": 500},
    )
    workspace = _find_by(response["workspaces"], "slug", config.workspace_slug)
    if workspace is not None:
        _require_active(workspace, "workspace", config.workspace_slug)
        return workspace, "reused"

    payload = {"slug": config.workspace_slug, "display_name": config.workspace_display_name}
    return client.post("/v1/admin/workspaces", token=config.admin_token, payload=payload)[
        "workspace"
    ], "created"


def _ensure_application(
    client: GrantoraClient,
    config: DemoSeedConfig,
    workspace_id: str,
) -> tuple[JSONDict, Action]:
    response = client.get(
        "/v1/admin/applications",
        token=config.admin_token,
        query={"workspace_id": workspace_id, "include_disabled": True, "limit": 500},
    )
    application = _find_by(response["applications"], "slug", config.application_slug)
    expected = {"provider_type": config.application_provider_type, "workspace_id": workspace_id}
    if application is not None:
        _require_active(application, "application", config.application_slug)
        _require_fields(application, expected, "application", config.application_slug)
        return application, "reused"

    payload = {
        "workspace_id": workspace_id,
        "slug": config.application_slug,
        "display_name": config.application_display_name,
        "provider_type": config.application_provider_type,
        "base_url": config.application_base_url,
    }
    return client.post("/v1/admin/applications", token=config.admin_token, payload=payload)[
        "application"
    ], "created"


def _ensure_user(
    client: GrantoraClient,
    config: DemoSeedConfig,
    workspace_id: str,
) -> tuple[JSONDict, Action]:
    response = client.get(
        "/v1/admin/users",
        token=config.admin_token,
        query={"workspace_id": workspace_id, "include_disabled": True, "limit": 500},
    )
    user = _find_by(response["users"], "external_id", config.user_external_id)
    if user is not None:
        _require_active(user, "user", config.user_external_id)
        return user, "reused"

    payload = {
        "workspace_id": workspace_id,
        "external_id": config.user_external_id,
        "display_name": config.user_display_name,
    }
    return client.post("/v1/admin/users", token=config.admin_token, payload=payload)[
        "user"
    ], "created"


def _ensure_capability(
    client: GrantoraClient,
    config: DemoSeedConfig,
    workspace_id: str,
    application_id: str,
) -> tuple[JSONDict, Action]:
    response = client.get(
        "/v1/admin/capabilities",
        token=config.admin_token,
        query={"workspace_id": workspace_id, "include_disabled": True, "limit": 500},
    )
    capability = _find_by(response["capabilities"], "id", config.capability_id)
    expected = {
        "workspace_id": workspace_id,
        "application_instance_id": application_id,
        "provider_type": config.application_provider_type,
        "adapter": config.application_provider_type,
        "operation": "phonebook.search",
        "auth_mode": "user",
        "risk_class": "read_only",
    }
    if capability is not None:
        _require_active(capability, "capability", config.capability_id)
        _require_fields(capability, expected, "capability", config.capability_id)
        return capability, "reused"

    payload = {
        "id": config.capability_id,
        "workspace_id": workspace_id,
        "application_instance_id": application_id,
        "name": config.capability_name,
        "version": 1,
        "provider_type": config.application_provider_type,
        "adapter": config.application_provider_type,
        "operation": "phonebook.search",
        "auth_mode": "user",
        "risk_class": "read_only",
        "input_schema": _phonebook_input_schema(),
        "output_schema": _phonebook_output_schema(),
    }
    return client.post("/v1/admin/capabilities", token=config.admin_token, payload=payload)[
        "capability"
    ], "created"


def _ensure_permissions(client: GrantoraClient, config: DemoSeedConfig) -> None:
    response = client.get(
        "/v1/admin/permissions",
        token=config.admin_token,
        query={"limit": 500, "offset": 0},
    )
    existing_codes = {permission["code"] for permission in response["permissions"]}
    missing_codes = sorted(set(config.role_permission_codes) - existing_codes)
    if missing_codes:
        raise WorkflowError(f"Default permissions are missing: {', '.join(missing_codes)}")


def _ensure_role(
    client: GrantoraClient,
    config: DemoSeedConfig,
    workspace_id: str,
) -> tuple[JSONDict, Action]:
    response = client.get(
        "/v1/admin/roles",
        token=config.admin_token,
        query={"workspace_id": workspace_id, "include_disabled": True, "limit": 500},
    )
    role = _find_by(response["roles"], "slug", config.role_slug)
    if role is not None:
        _require_active(role, "role", config.role_slug)
        missing_permissions = sorted(
            set(config.role_permission_codes) - set(role["permission_codes"])
        )
        if missing_permissions:
            raise WorkflowError(
                f"Demo role {config.role_slug!r} exists without permissions: "
                f"{', '.join(missing_permissions)}"
            )
        return role, "reused"

    payload = {
        "workspace_id": workspace_id,
        "slug": config.role_slug,
        "display_name": config.role_display_name,
        "permission_codes": list(config.role_permission_codes),
    }
    return client.post("/v1/admin/roles", token=config.admin_token, payload=payload)[
        "role"
    ], "created"


def _ensure_agent(
    client: GrantoraClient,
    config: DemoSeedConfig,
    workspace_id: str,
) -> tuple[JSONDict, str | None, Action]:
    response = client.get(
        "/v1/admin/agents",
        token=config.admin_token,
        query={"workspace_id": workspace_id, "include_disabled": True, "limit": 500},
    )
    agent = _find_by(response["agents"], "slug", config.agent_slug)
    if agent is not None:
        _require_active(agent, "agent", config.agent_slug)
        return agent, config.existing_agent_token, "reused"

    payload = {
        "workspace_id": workspace_id,
        "slug": config.agent_slug,
        "display_name": config.agent_display_name,
    }
    response = client.post("/v1/admin/agents", token=config.admin_token, payload=payload)
    return response["agent"], response["token"], "created"


def _ensure_binding(
    client: GrantoraClient,
    config: DemoSeedConfig,
    *,
    workspace_id: str,
    agent_id: str,
    user_id: str,
    role_id: str,
) -> tuple[JSONDict, Action]:
    query = {
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "user_id": user_id,
        "capability_id": config.capability_id,
        "role_id": role_id,
        "include_disabled": True,
        "limit": 500,
    }
    response = client.get("/v1/admin/bindings", token=config.admin_token, query=query)
    binding = response["bindings"][0] if response["bindings"] else None
    if binding is not None:
        _require_active(binding, "binding", config.capability_id)
        return binding, "reused"

    payload = {
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "user_id": user_id,
        "capability_id": config.capability_id,
        "role_id": role_id,
    }
    return client.post("/v1/admin/bindings", token=config.admin_token, payload=payload)[
        "binding"
    ], "created"


def _ensure_secret(
    client: GrantoraClient,
    config: DemoSeedConfig,
    *,
    workspace_id: str,
    application_id: str,
    user_id: str,
) -> tuple[JSONDict, Action]:
    query = {
        "workspace_id": workspace_id,
        "application_instance_id": application_id,
        "owner_type": "user",
        "owner_id": user_id,
        "limit": 500,
    }
    response = client.get("/v1/admin/secrets", token=config.admin_token, query=query)
    secret = response["secrets"][0] if response["secrets"] else None
    if secret is not None:
        _require_active(secret, "secret", f"{config.user_external_id} upstream secret")
        return secret, "reused"

    payload = {
        "workspace_id": workspace_id,
        "application_instance_id": application_id,
        "owner_type": "user",
        "owner_id": user_id,
        "secret_type": config.secret_type,
        "value": config.upstream_secret,
    }
    return client.post("/v1/admin/secrets", token=config.admin_token, payload=payload)[
        "secret"
    ], "created"


def _check_health(client: GrantoraClient) -> CheckReport:
    body = client.get("/healthz")
    if body.get("status") != "ok":
        raise WorkflowError("/healthz did not report ok")
    return CheckReport("healthz", "ok", "process is alive")


def _check_ready(client: GrantoraClient) -> CheckReport:
    body = client.get("/readyz")
    if body.get("status") != "ok" or body.get("checks", {}).get("database") != "ok":
        raise WorkflowError("/readyz did not report database readiness")
    return CheckReport("readyz", "ok", "database is reachable")


def _check_apisix_sync(client: GrantoraClient, config: SmokeConfig) -> CheckReport:
    body = client.post("/v1/admin/apisix/sync", token=config.admin_token)
    if body.get("status") != "ok":
        raise WorkflowError("APISIX sync did not report ok")
    detail = f"checked {body.get('checked_routes', 0)} route(s)"
    return CheckReport("apisix-sync", "ok", detail)


def _check_discovery(client: GrantoraClient, config: SmokeConfig) -> CheckReport:
    body = client.get(
        "/v1/capabilities",
        token=config.agent_token,
        query={"user": config.user_external_id},
    )
    capability_ids = [capability["id"] for capability in body.get("capabilities", [])]
    if config.capability_id not in capability_ids:
        raise WorkflowError(
            f"Runtime discovery did not include required capability {config.capability_id!r}"
        )
    return CheckReport("runtime-discovery", "ok", f"found {config.capability_id}")


def _check_invocation(client: GrantoraClient, config: SmokeConfig) -> CheckReport:
    body = client.post(
        f"/v1/invoke/{config.capability_id}",
        token=config.agent_token,
        payload={
            "user": config.user_external_id,
            "input": config.invocation_input or {"query": "Mario", "limit": 5},
        },
    )
    if body.get("status") != "ok" or body.get("capability") != config.capability_id:
        raise WorkflowError("Mock invocation did not return a successful capability response")
    return CheckReport("mock-invocation", "ok", "adapter returned status ok")


def _check_filtered_openapi(client: GrantoraClient, config: SmokeConfig) -> CheckReport:
    body = client.get(
        "/v1/capabilities/openapi.json",
        token=config.agent_token,
        query={"user": config.user_external_id},
    )
    path = f"/v1/invoke/{config.capability_id}"
    operation = body.get("paths", {}).get(path, {}).get("post", {})
    if operation.get("x-grantora-capability-id") != config.capability_id:
        raise WorkflowError(
            f"Filtered OpenAPI did not include required capability {config.capability_id!r}"
        )
    if operation.get("x-grantora-tool-name") != capability_tool_name(config.capability_id):
        raise WorkflowError("Filtered OpenAPI did not include the expected tool name")
    return CheckReport("filtered-openapi", "ok", f"found {config.capability_id}")


def _check_mcp_tools(client: GrantoraClient, config: SmokeConfig) -> CheckReport:
    body = client.get(
        "/v1/mcp/tools",
        token=config.agent_token,
        query={"user": config.user_external_id},
    )
    tool_name = capability_tool_name(config.capability_id)
    for tool in body.get("tools", []):
        if (
            tool.get("name") == tool_name
            and tool.get("_meta", {}).get("grantora/capability_id") == config.capability_id
        ):
            return CheckReport("mcp-tool-discovery", "ok", f"found {tool_name}")
    raise WorkflowError(f"MCP tool discovery did not include required tool {tool_name!r}")


def _check_mcp_call(client: GrantoraClient, config: SmokeConfig) -> CheckReport:
    body = client.post(
        "/v1/mcp/call",
        token=config.agent_token,
        payload={
            "user": config.user_external_id,
            "name": capability_tool_name(config.capability_id),
            "arguments": config.invocation_input or {"query": "Mario", "limit": 5},
        },
    )
    if body.get("isError") is not False:
        raise WorkflowError("MCP tool call reported an error")
    if body.get("_meta", {}).get("grantora/capability_id") != config.capability_id:
        raise WorkflowError("MCP tool call did not return the expected capability metadata")
    return CheckReport("mcp-tool-call", "ok", "tool call returned normalized data")


def _phonebook_input_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
        "additionalProperties": False,
    }


def _phonebook_output_schema() -> JSONDict:
    return {
        "type": "object",
        "properties": {"contacts": {"type": "array"}},
        "required": ["contacts"],
        "additionalProperties": False,
    }


def _report(name: str, label: str, action: Action, identifier: str) -> ResourceReport:
    return ResourceReport(name=name, label=label, action=action, identifier=identifier)


def _find_by(items: list[JSONDict], field: str, value: object) -> JSONDict | None:
    return next((item for item in items if item.get(field) == value), None)


def _require_active(resource: JSONDict, label: str, name: str) -> None:
    status = resource.get("status")
    if status != ACTIVE_STATUS:
        raise WorkflowError(
            f"Demo {label} {name!r} already exists with status {status!r}; "
            "reactivate or remove it before running demo-seed."
        )


def _require_fields(resource: JSONDict, expected: dict[str, object], label: str, name: str) -> None:
    for field, expected_value in expected.items():
        actual_value = resource.get(field)
        if actual_value != expected_value:
            raise WorkflowError(
                f"Demo {label} {name!r} has {field}={actual_value!r}; expected {expected_value!r}."
            )


def _build_url(
    base_url: str,
    path: str,
    query: dict[str, object | None] | None = None,
) -> str:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    if not query:
        return url

    pairs = []
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        else:
            pairs.append((key, str(value)))
    if not pairs:
        return url
    return f"{url}?{urllib.parse.urlencode(pairs)}"


def _decode_json_response(raw_body: bytes) -> JSONDict:
    if not raw_body:
        return {}
    try:
        document = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowError("Grantora returned a non-JSON response") from exc
    if not isinstance(document, dict):
        raise WorkflowError("Grantora returned a JSON response that was not an object")
    return document


def _safe_http_error_message(method: str, path: str, exc: urllib.error.HTTPError) -> str:
    detail = f"{method} {path} returned HTTP {exc.code}"
    raw_body = exc.read()
    if not raw_body:
        return detail
    try:
        document = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return detail
    error = document.get("error") if isinstance(document, dict) else None
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        if code and message:
            return f"{detail} ({code}: {message})"
    return detail


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        raise WorkflowError(f"Set {name} before running this command.")
    return value


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise WorkflowError(f"{name} must be a number") from exc


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise WorkflowError(f"{name} must be an integer") from exc
