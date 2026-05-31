from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, Query, Request, status
from sqlalchemy.orm import Session

from grantora.adapters import (
    AdapterRegistry,
    AgentContext,
    ApplicationContext,
    CapabilityContext,
    InvocationContext,
    UserContext,
    WorkspaceContext,
)
from grantora.api.errors import GrantoraAPIError, get_request_id
from grantora.audit import record_audit_event
from grantora.auth.dependencies import AuthenticatedAgent, DatabaseSession
from grantora.capabilities import (
    DESCRIBE_PERMISSION,
    CapabilitySchemaValidationError,
    invoke_permission_for_risk_class,
    validate_json_schema,
)
from grantora.db.models import ACTIVE_STATUS, Agent, Capability, User
from grantora.db.queries import (
    get_active_binding,
    get_active_capability_by_id,
    get_active_user_by_external_id,
    list_active_capabilities_for_agent_user,
    role_grants_permission,
)
from grantora.openapi import build_capability_openapi, build_runtime_openapi
from grantora.schemas import (
    AgentSummary,
    CapabilityInvokeRequest,
    CapabilityInvokeResponse,
    CapabilityListResponse,
    CapabilitySummary,
    MeResponse,
    WorkspaceSummary,
)
from grantora.secrets import SecretResolutionError, resolve_secret_material
from grantora.usage import record_usage_event

router = APIRouter(prefix="/v1", tags=["runtime"])
CAPABILITY_DENIED_MESSAGE = "Capability is not allowed for this agent and user"


@router.get("/me", response_model=MeResponse)
def get_me(agent: AuthenticatedAgent) -> MeResponse:
    return MeResponse(
        agent=AgentSummary.model_validate(agent),
        workspace=WorkspaceSummary.model_validate(agent.workspace),
    )


@router.get("/capabilities", response_model=CapabilityListResponse)
def list_capabilities(
    agent: AuthenticatedAgent,
    session: DatabaseSession,
    user: str = Query(min_length=1),
) -> CapabilityListResponse:
    selected_user = get_active_user_by_external_id(session, agent.workspace_id, user)
    if selected_user is None:
        return CapabilityListResponse(capabilities=[])

    return CapabilityListResponse(
        capabilities=[
            CapabilitySummary.model_validate(capability)
            for capability in _list_visible_capabilities(session, agent, selected_user)
        ]
    )


@router.get("/openapi.json")
def get_runtime_openapi(request: Request, agent: AuthenticatedAgent) -> dict[str, Any]:
    return build_runtime_openapi(request.app.routes)


@router.get("/capabilities/openapi.json")
def get_capability_openapi(
    agent: AuthenticatedAgent,
    session: DatabaseSession,
    user: str = Query(min_length=1),
) -> dict[str, Any]:
    selected_user = get_active_user_by_external_id(session, agent.workspace_id, user)
    if selected_user is None:
        return build_capability_openapi([], user=user)

    return build_capability_openapi(
        _list_visible_capabilities(session, agent, selected_user),
        user=user,
    )


@router.post("/invoke/{capability_id}", response_model=CapabilityInvokeResponse)
async def invoke_capability(
    capability_id: str,
    payload: CapabilityInvokeRequest,
    request: Request,
    agent: AuthenticatedAgent,
    session: DatabaseSession,
) -> CapabilityInvokeResponse:
    started_at = perf_counter()
    request_id = get_request_id(request)
    selected_user = get_active_user_by_external_id(session, agent.workspace_id, payload.user)
    if selected_user is None:
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=None,
            capability=None,
            capability_id=capability_id,
            decision="deny",
            usage_status="denied",
            http_status=status.HTTP_403_FORBIDDEN,
            error_code="capability_denied",
            message=CAPABILITY_DENIED_MESSAGE,
        )

    capability = get_active_capability_by_id(session, agent.workspace_id, capability_id)
    if capability is None or capability.application_instance.status != ACTIVE_STATUS:
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=None,
            capability_id=capability_id,
            decision="deny",
            usage_status="denied",
            http_status=status.HTTP_403_FORBIDDEN,
            error_code="capability_denied",
            message=CAPABILITY_DENIED_MESSAGE,
        )

    binding = get_active_binding(
        session,
        agent.workspace_id,
        agent.id,
        selected_user.id,
        capability.id,
    )
    permission_code = invoke_permission_for_risk_class(capability.risk_class)
    if (
        binding is None
        or permission_code is None
        or not role_grants_permission(
            session,
            binding.role_id,
            permission_code,
        )
    ):
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=capability,
            capability_id=capability_id,
            decision="deny",
            usage_status="denied",
            http_status=status.HTTP_403_FORBIDDEN,
            error_code="capability_denied",
            message=CAPABILITY_DENIED_MESSAGE,
        )

    try:
        validate_json_schema(
            payload.input,
            capability.input_schema,
            validation_error_code="invalid_capability_input",
            validation_message="Capability input did not match the capability schema",
        )
    except CapabilitySchemaValidationError as exc:
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=capability,
            capability_id=capability_id,
            decision="allow",
            usage_status="error",
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code=exc.code,
            message=exc.message,
        )

    try:
        secret = resolve_secret_material(
            session, request.app.state.settings, capability, selected_user
        )
    except SecretResolutionError as exc:
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=capability,
            capability_id=capability_id,
            decision="deny",
            usage_status="denied",
            http_status=status.HTTP_424_FAILED_DEPENDENCY,
            error_code=exc.code,
            message=exc.message,
        )

    adapter_registry = _get_adapter_registry(request)
    adapter = adapter_registry.get(capability.adapter)
    if adapter is None:
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=capability,
            capability_id=capability_id,
            decision="allow",
            usage_status="error",
            http_status=status.HTTP_502_BAD_GATEWAY,
            error_code="adapter_not_found",
            message="Capability adapter is unavailable",
        )

    context = _build_invocation_context(request_id, agent, selected_user, capability)
    try:
        result = await adapter.invoke(capability, payload.input, context, secret)
    except Exception as exc:
        _record_invocation_attempt(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=capability,
            capability_id=capability_id,
            decision="allow",
            outcome="error",
            error_code="adapter_error",
            usage_status="error",
        )
        raise GrantoraAPIError(
            status.HTTP_502_BAD_GATEWAY,
            "adapter_error",
            "Capability adapter returned an error",
        ) from exc

    if result.status != "ok":
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=capability,
            capability_id=capability_id,
            decision="allow",
            usage_status="error",
            http_status=status.HTTP_502_BAD_GATEWAY,
            error_code=result.error_code or "adapter_error",
            message=result.safe_message or "Capability adapter returned an error",
        )

    try:
        validate_json_schema(
            result.data,
            capability.output_schema,
            validation_error_code="adapter_invalid_response",
            validation_message="Capability adapter returned invalid data",
        )
    except CapabilitySchemaValidationError as exc:
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=capability,
            capability_id=capability_id,
            decision="allow",
            usage_status="error",
            http_status=status.HTTP_502_BAD_GATEWAY,
            error_code=exc.code,
            message=exc.message,
        )

    _record_invocation_attempt(
        session,
        request,
        started_at,
        request_id=request_id,
        agent=agent,
        user=selected_user,
        capability=capability,
        capability_id=capability_id,
        decision="allow",
        outcome="success",
        error_code=None,
        usage_status="success",
        units=max(result.usage_units, 1),
    )
    return CapabilityInvokeResponse(
        request_id=request_id,
        capability=capability.id,
        status="ok",
        data=result.data,
    )


def _get_adapter_registry(request: Request) -> AdapterRegistry:
    adapter_registry = getattr(request.app.state, "adapters", None)
    if isinstance(adapter_registry, AdapterRegistry):
        return adapter_registry
    return AdapterRegistry()


def _list_visible_capabilities(session: Session, agent: Agent, user: User) -> list[Capability]:
    visible_capabilities = []
    for capability in list_active_capabilities_for_agent_user(
        session,
        agent.workspace_id,
        agent.id,
        user.id,
    ):
        binding = get_active_binding(
            session,
            agent.workspace_id,
            agent.id,
            user.id,
            capability.id,
        )
        permission_code = invoke_permission_for_risk_class(capability.risk_class)
        if (
            binding is None
            or permission_code is None
            or not role_grants_permission(session, binding.role_id, DESCRIBE_PERMISSION)
            or not role_grants_permission(session, binding.role_id, permission_code)
        ):
            continue
        visible_capabilities.append(capability)

    return visible_capabilities


def _build_invocation_context(
    request_id: str,
    agent: Agent,
    user: User,
    capability: Capability,
) -> InvocationContext:
    application = capability.application_instance
    return InvocationContext(
        request_id=request_id,
        workspace=WorkspaceContext(id=agent.workspace.id, slug=agent.workspace.slug),
        agent=AgentContext(id=agent.id, slug=agent.slug),
        user=UserContext(id=user.id, external_id=user.external_id),
        application=ApplicationContext(
            id=application.id,
            provider_type=application.provider_type,
            base_url=application.base_url,
        ),
        capability=CapabilityContext(id=capability.id, operation=capability.operation),
    )


def _record_and_raise_invocation_error(
    session: Session,
    request: Request,
    started_at: float,
    *,
    request_id: str,
    agent: Agent,
    user: User | None,
    capability: Capability | None,
    capability_id: str,
    decision: str,
    usage_status: str,
    http_status: int,
    error_code: str,
    message: str,
) -> None:
    _record_invocation_attempt(
        session,
        request,
        started_at,
        request_id=request_id,
        agent=agent,
        user=user,
        capability=capability,
        capability_id=capability_id,
        decision=decision,
        outcome="error",
        error_code=error_code,
        usage_status=usage_status,
    )
    raise GrantoraAPIError(http_status, error_code, message)


def _record_invocation_attempt(
    session: Session,
    request: Request,
    started_at: float,
    *,
    request_id: str,
    agent: Agent,
    user: User | None,
    capability: Capability | None,
    capability_id: str,
    decision: str,
    outcome: str,
    error_code: str | None,
    usage_status: str,
    units: int = 1,
) -> None:
    latency_ms = max(int((perf_counter() - started_at) * 1000), 0)
    application_instance_id = capability.application_instance_id if capability is not None else None
    record_audit_event(
        session,
        request_id=request_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        user_id=user.id if user is not None else None,
        capability_id=capability_id,
        application_instance_id=application_instance_id,
        decision=decision,
        outcome=outcome,
        error_code=error_code,
        latency_ms=latency_ms,
        remote_addr=request.client.host if request.client else None,
    )
    record_usage_event(
        session,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        user_id=user.id if user is not None else None,
        capability_id=capability_id,
        application_instance_id=application_instance_id,
        units=units,
        status=usage_status,
        latency_ms=latency_ms,
    )
    session.commit()
