from __future__ import annotations

import json
import logging
from datetime import datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, select
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
from grantora.db.models import ACTIVE_STATUS, Agent, Capability, UsageEvent, User
from grantora.db.queries import (
    get_active_binding,
    get_active_capability_by_id,
    get_active_user_by_external_id,
    list_active_capabilities_for_agent_user,
    role_grants_permission,
)
from grantora.metrics import record_authorization_denied, record_upstream_result
from grantora.openapi import (
    build_capability_openapi,
    build_mcp_tool_list,
    build_runtime_openapi,
    capability_tool_name,
)
from grantora.schemas import (
    AgentSummary,
    CapabilityInvokeRequest,
    CapabilityInvokeResponse,
    CapabilityListResponse,
    CapabilitySummary,
    MCPTextContent,
    MCPToolCallRequest,
    MCPToolCallResponse,
    MCPToolListResponse,
    MeResponse,
    RuntimeUsageAggregateSummary,
    RuntimeUsageEventSummary,
    UsageMeResponse,
    WorkspaceSummary,
)
from grantora.secrets import SecretResolutionError, resolve_secret_material
from grantora.usage import record_usage_event

router = APIRouter(prefix="/v1", tags=["runtime"])
CAPABILITY_DENIED_MESSAGE = "Capability is not allowed for this agent and user"
LOGGER = logging.getLogger("grantora.runtime")


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
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CapabilityListResponse:
    selected_user = get_active_user_by_external_id(session, agent.workspace_id, user)
    if selected_user is None:
        return CapabilityListResponse(capabilities=[], limit=limit, offset=offset)

    visible_capabilities = _list_visible_capabilities(session, agent, selected_user)

    return CapabilityListResponse(
        capabilities=[
            CapabilitySummary.model_validate(capability)
            for capability in visible_capabilities[offset : offset + limit]
        ],
        limit=limit,
        offset=offset,
    )


@router.get("/openapi.json")
def get_runtime_openapi(request: Request, agent: AuthenticatedAgent) -> dict[str, Any]:
    settings = request.app.state.settings
    return build_runtime_openapi(request.app.routes, public_base_url=settings.public_base_url)


@router.get("/capabilities/openapi.json")
def get_capability_openapi(
    request: Request,
    agent: AuthenticatedAgent,
    session: DatabaseSession,
    user: str = Query(min_length=1),
) -> dict[str, Any]:
    selected_user = get_active_user_by_external_id(session, agent.workspace_id, user)
    if selected_user is None:
        return build_capability_openapi(
            [],
            user=user,
            public_base_url=request.app.state.settings.public_base_url,
        )

    return build_capability_openapi(
        _list_visible_capabilities(session, agent, selected_user),
        user=user,
        public_base_url=request.app.state.settings.public_base_url,
    )


@router.get("/mcp/tools", response_model=MCPToolListResponse)
def list_mcp_tools(
    agent: AuthenticatedAgent,
    session: DatabaseSession,
    user: str = Query(min_length=1),
) -> dict[str, Any]:
    selected_user = get_active_user_by_external_id(session, agent.workspace_id, user)
    if selected_user is None:
        return build_mcp_tool_list([])

    return build_mcp_tool_list(_list_visible_capabilities(session, agent, selected_user))


@router.post("/mcp/call", response_model=MCPToolCallResponse)
async def call_mcp_tool(
    payload: MCPToolCallRequest,
    request: Request,
    agent: AuthenticatedAgent,
    session: DatabaseSession,
) -> MCPToolCallResponse:
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
            capability_id=payload.name,
            decision="deny",
            usage_status="denied",
            http_status=status.HTTP_403_FORBIDDEN,
            error_code="capability_denied",
            message=CAPABILITY_DENIED_MESSAGE,
        )

    capability = _get_mcp_capability_by_tool_name(session, agent, selected_user, payload.name)
    if capability is None:
        _record_and_raise_invocation_error(
            session,
            request,
            started_at,
            request_id=request_id,
            agent=agent,
            user=selected_user,
            capability=None,
            capability_id=payload.name,
            decision="deny",
            usage_status="denied",
            http_status=status.HTTP_403_FORBIDDEN,
            error_code="capability_denied",
            message=CAPABILITY_DENIED_MESSAGE,
        )

    invocation = await _invoke_capability_by_id(
        capability.id,
        CapabilityInvokeRequest(user=payload.user, input=payload.arguments),
        request,
        agent,
        session,
    )
    return _mcp_response_from_invocation(invocation)


@router.get("/usage/me", response_model=UsageMeResponse)
def get_usage_me(
    agent: AuthenticatedAgent,
    session: DatabaseSession,
    user_id: UUID | None = None,
    capability_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> UsageMeResponse:
    filters = _usage_filters_for_agent(
        agent,
        user_id=user_id,
        capability_id=capability_id,
        status_filter=status_filter,
        start_time=start_time,
        end_time=end_time,
    )
    usage_statement = (
        select(UsageEvent)
        .where(*filters)
        .order_by(UsageEvent.timestamp.desc(), UsageEvent.id.desc())
        .offset(offset)
        .limit(limit)
    )
    summary_statement = (
        select(
            UsageEvent.workspace_id,
            UsageEvent.agent_id,
            UsageEvent.user_id,
            UsageEvent.capability_id,
            UsageEvent.status,
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.units), 0),
        )
        .where(*filters)
        .group_by(
            UsageEvent.workspace_id,
            UsageEvent.agent_id,
            UsageEvent.user_id,
            UsageEvent.capability_id,
            UsageEvent.status,
        )
        .order_by(UsageEvent.status)
    )
    summaries = [
        RuntimeUsageAggregateSummary(
            workspace_id=row[0],
            agent_id=row[1],
            user_id=row[2],
            capability_id=row[3],
            status=row[4],
            events=row[5],
            total_units=row[6],
        )
        for row in session.execute(summary_statement).all()
    ]
    return UsageMeResponse(
        usage=[
            RuntimeUsageEventSummary.model_validate(event)
            for event in session.scalars(usage_statement)
        ],
        summaries=summaries,
        limit=limit,
        offset=offset,
    )


@router.post("/invoke/{capability_id}", response_model=CapabilityInvokeResponse)
async def invoke_capability(
    capability_id: str,
    payload: CapabilityInvokeRequest,
    request: Request,
    agent: AuthenticatedAgent,
    session: DatabaseSession,
) -> CapabilityInvokeResponse:
    return await _invoke_capability_by_id(capability_id, payload, request, agent, session)


async def _invoke_capability_by_id(
    capability_id: str,
    payload: CapabilityInvokeRequest,
    request: Request,
    agent: Agent,
    session: Session,
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
        record_upstream_result(
            workspace=str(agent.workspace_id),
            provider=capability.provider_type,
            status_code=None,
            error_code="adapter_error",
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
            outcome="error",
            error_code="adapter_error",
            usage_status="error",
        )
        raise GrantoraAPIError(
            status.HTTP_502_BAD_GATEWAY,
            "adapter_error",
            "Capability adapter returned an error",
        ) from exc

    record_upstream_result(
        workspace=str(agent.workspace_id),
        provider=capability.provider_type,
        status_code=result.upstream_status,
        error_code=result.error_code if result.status != "ok" else None,
    )

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


def _get_mcp_capability_by_tool_name(
    session: Session,
    agent: Agent,
    user: User,
    tool_name: str,
) -> Capability | None:
    for capability in sorted(
        _list_visible_capabilities(session, agent, user),
        key=lambda visible_capability: visible_capability.id,
    ):
        if capability_tool_name(capability.id) == tool_name:
            return capability
    return None


def _mcp_response_from_invocation(invocation: CapabilityInvokeResponse) -> MCPToolCallResponse:
    return MCPToolCallResponse(
        content=[
            MCPTextContent(
                type="text",
                text=json.dumps(invocation.data, separators=(",", ":"), sort_keys=True),
            )
        ],
        structured_content=invocation.data,
        is_error=False,
        meta={
            "grantora/request_id": invocation.request_id,
            "grantora/capability_id": invocation.capability,
        },
    )


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


def _usage_filters_for_agent(
    agent: Agent,
    *,
    user_id: UUID | None,
    capability_id: str | None,
    status_filter: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
) -> list[object]:
    filters: list[object] = [
        UsageEvent.workspace_id == agent.workspace_id,
        UsageEvent.agent_id == agent.id,
    ]
    if user_id is not None:
        filters.append(UsageEvent.user_id == user_id)
    if capability_id is not None:
        filters.append(UsageEvent.capability_id == capability_id)
    if status_filter is not None:
        filters.append(UsageEvent.status == status_filter)
    if start_time is not None:
        filters.append(UsageEvent.timestamp >= start_time)
    if end_time is not None:
        filters.append(UsageEvent.timestamp <= end_time)
    return filters


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
    _set_request_observability_context(request, agent, user, capability, capability_id)
    if decision == "deny":
        record_authorization_denied(
            workspace=str(agent.workspace_id),
            reason=error_code or "denied",
        )
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
    _log_invocation_attempt(
        request,
        request_id=request_id,
        agent=agent,
        user=user,
        capability=capability,
        capability_id=capability_id,
        decision=decision,
        outcome=outcome,
        usage_status=usage_status,
        error_code=error_code,
        latency_ms=latency_ms,
    )


def _set_request_observability_context(
    request: Request,
    agent: Agent,
    user: User | None,
    capability: Capability | None,
    capability_id: str,
) -> None:
    request.state.workspace_id = str(agent.workspace_id)
    request.state.agent_id = str(agent.id)
    request.state.user_id = str(user.id) if user is not None else None
    request.state.capability_id = capability_id
    request.state.provider_type = capability.provider_type if capability is not None else None


def _log_invocation_attempt(
    request: Request,
    *,
    request_id: str,
    agent: Agent,
    user: User | None,
    capability: Capability | None,
    capability_id: str,
    decision: str,
    outcome: str,
    usage_status: str,
    error_code: str | None,
    latency_ms: int,
) -> None:
    extra = {
        "request_id": request_id,
        "trace_id": getattr(request.state, "trace_id", None),
        "span_id": getattr(request.state, "span_id", None),
        "workspace_id": str(agent.workspace_id),
        "agent_id": str(agent.id),
        "user_id": str(user.id) if user is not None else None,
        "capability_id": capability_id,
        "provider_type": capability.provider_type if capability is not None else None,
        "decision": decision,
        "outcome": outcome,
        "usage_status": usage_status,
        "error_code": error_code,
        "duration_ms": latency_ms,
    }
    if outcome == "success":
        LOGGER.info("runtime invocation succeeded", extra=extra)
        return
    if decision == "deny":
        LOGGER.warning("runtime invocation denied", extra=extra)
        return
    LOGGER.error("runtime invocation failed", extra=extra)
