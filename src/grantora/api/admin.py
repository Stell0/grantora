from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from grantora.adapters.templates import get_capability_template, list_capability_templates
from grantora.api.errors import GrantoraAPIError, get_request_id
from grantora.apisix import (
    ApisixAdminClient,
    ApisixRouteDriftResult,
    ApisixSyncResult,
    check_apisix_route_drift,
    get_apisix_sync_status,
    reconcile_apisix_routes,
)
from grantora.audit import record_audit_event
from grantora.auth import TOKEN_HASH_ALGORITHM, create_agent_token, hash_token
from grantora.auth.dependencies import AdminBootstrap, AdminPrincipal, DatabaseSession
from grantora.capabilities import (
    CapabilitySchemaValidationError,
    check_json_schema,
    validate_capability_definition,
)
from grantora.capabilities.permissions import DESCRIBE_PERMISSION, RISK_CLASS_PERMISSIONS
from grantora.config import Settings
from grantora.db.models import (
    ACTIVE_STATUS,
    REVOKED_STATUS,
    Agent,
    ApisixSyncStatus,
    ApplicationInstance,
    AuditEvent,
    Binding,
    Capability,
    Permission,
    Role,
    RolePermission,
    Secret,
    UsageEvent,
    User,
    Workspace,
)
from grantora.db.queries import get_active_workspace_by_id
from grantora.schemas import (
    AdminAgentCreateRequest,
    AdminAgentCreateResponse,
    AdminAgentListResponse,
    AdminAgentResponse,
    AdminAgentUpdateRequest,
    AdminApisixStatusResponse,
    AdminApisixSyncResponse,
    AdminApplicationCreateRequest,
    AdminApplicationListResponse,
    AdminApplicationResponse,
    AdminAuditListResponse,
    AdminBindingCreateRequest,
    AdminBindingListResponse,
    AdminBindingResponse,
    AdminCapabilityCreateRequest,
    AdminCapabilityFromTemplateRequest,
    AdminCapabilityListResponse,
    AdminCapabilityResponse,
    AdminCapabilityTemplateListResponse,
    AdminLifecycleStatusUpdateRequest,
    AdminPermissionCreateRequest,
    AdminPermissionListResponse,
    AdminPermissionResponse,
    AdminRoleCreateRequest,
    AdminRoleListResponse,
    AdminRoleResponse,
    AdminSecretCreateRequest,
    AdminSecretListResponse,
    AdminSecretResponse,
    AdminSecretRotateRequest,
    AdminSecretRotationResponse,
    AdminSecretStatusUpdateRequest,
    AdminUsageListResponse,
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserResponse,
    AdminWorkspaceCreateRequest,
    AdminWorkspaceListResponse,
    AdminWorkspaceResponse,
    AgentAdminSummary,
    ApisixRouteDriftSummary,
    ApisixSyncErrorSummary,
    ApplicationAdminSummary,
    AuditEventAdminSummary,
    BindingAdminSummary,
    CapabilityAdminSummary,
    CapabilityTemplateAdminSummary,
    PermissionAdminSummary,
    RoleAdminSummary,
    SecretAdminSummary,
    UsageAggregateSummary,
    UsageEventAdminSummary,
    UserAdminSummary,
    WorkspaceAdminSummary,
)
from grantora.secrets import SecretCipher
from grantora.secrets.stores import stored_external_secret_reference

router = APIRouter(prefix="/v1/admin", tags=["admin"])

DEFAULT_PERMISSION_DESCRIPTIONS = {
    DESCRIBE_PERMISSION: "Describe capabilities",
    RISK_CLASS_PERMISSIONS["read_only"]: "Invoke read-only capabilities",
    RISK_CLASS_PERMISSIONS["side_effect"]: "Invoke side-effecting capabilities",
    RISK_CLASS_PERMISSIONS["destructive"]: "Invoke destructive capabilities",
}
RAW_PASSTHROUGH_OPERATIONS = {"http.get", "http.post", "http.request", "raw.request"}
RAW_PASSTHROUGH_INPUT_FIELDS = {
    "headers",
    "method",
    "path",
    "raw_body",
    "upstream_path",
    "upstream_url",
    "url",
}


@router.post(
    "/workspaces",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminWorkspaceResponse,
)
def create_workspace(
    payload: AdminWorkspaceCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminWorkspaceResponse:
    _require_super_admin(_admin)
    workspace = Workspace(
        slug=payload.slug,
        display_name=payload.display_name,
        status=payload.status,
    )
    session.add(workspace)
    _flush_or_conflict(session, "workspace_conflict", "Workspace could not be created")
    _record_admin_audit_event(session, request, workspace_id=workspace.id)
    _commit_or_conflict(session, "workspace_conflict", "Workspace could not be created")
    return AdminWorkspaceResponse(workspace=WorkspaceAdminSummary.model_validate(workspace))


@router.get("/workspaces", response_model=AdminWorkspaceListResponse)
def list_workspaces(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    include_disabled: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminWorkspaceListResponse:
    statement = select(Workspace).order_by(Workspace.slug)
    if _admin.workspace_id is not None:
        statement = statement.where(Workspace.id == _admin.workspace_id)
    if not include_disabled:
        statement = statement.where(Workspace.status == ACTIVE_STATUS)
    workspaces = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminWorkspaceListResponse(
        workspaces=[WorkspaceAdminSummary.model_validate(workspace) for workspace in workspaces],
        limit=limit,
        offset=offset,
    )


@router.patch("/workspaces/{workspace_id}", response_model=AdminWorkspaceResponse)
def update_workspace_status(
    workspace_id: UUID,
    payload: AdminLifecycleStatusUpdateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminWorkspaceResponse:
    _require_admin_workspace(_admin, workspace_id)
    workspace = _get_workspace_or_404(session, workspace_id)
    workspace.status = payload.status
    _record_admin_audit_event(session, request, workspace_id=workspace.id)
    _commit_or_conflict(session, "workspace_conflict", "Workspace could not be updated")
    return AdminWorkspaceResponse(workspace=WorkspaceAdminSummary.model_validate(workspace))


@router.post(
    "/applications",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminApplicationResponse,
)
def create_application(
    payload: AdminApplicationCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminApplicationResponse:
    _require_admin_workspace(_admin, payload.workspace_id)
    workspace = _get_active_workspace_or_404(session, payload.workspace_id)
    application = ApplicationInstance(
        workspace=workspace,
        slug=payload.slug,
        display_name=payload.display_name,
        provider_type=payload.provider_type,
        base_url=payload.base_url,
        status=payload.status,
    )
    session.add(application)
    _flush_or_conflict(session, "application_conflict", "Application could not be created")
    _record_admin_audit_event(
        session,
        request,
        workspace_id=workspace.id,
        application_instance_id=application.id,
    )
    _commit_or_conflict(session, "application_conflict", "Application could not be created")
    return AdminApplicationResponse(application=ApplicationAdminSummary.model_validate(application))


@router.get("/applications", response_model=AdminApplicationListResponse)
def list_applications(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    include_disabled: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminApplicationListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    statement = select(ApplicationInstance).order_by(ApplicationInstance.slug)
    if workspace_id is not None:
        statement = statement.where(ApplicationInstance.workspace_id == workspace_id)
    if not include_disabled:
        statement = statement.where(ApplicationInstance.status == ACTIVE_STATUS)
    applications = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminApplicationListResponse(
        applications=[
            ApplicationAdminSummary.model_validate(application) for application in applications
        ],
        limit=limit,
        offset=offset,
    )


@router.patch("/applications/{application_id}", response_model=AdminApplicationResponse)
def update_application_status(
    application_id: UUID,
    payload: AdminLifecycleStatusUpdateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminApplicationResponse:
    application = _get_application_or_404(session, application_id)
    _require_admin_workspace(_admin, application.workspace_id)
    if payload.status == ACTIVE_STATUS:
        _get_active_workspace_or_404(session, application.workspace_id)
    application.status = payload.status
    _record_admin_audit_event(
        session,
        request,
        workspace_id=application.workspace_id,
        application_instance_id=application.id,
    )
    _commit_or_conflict(session, "application_conflict", "Application could not be updated")
    return AdminApplicationResponse(application=ApplicationAdminSummary.model_validate(application))


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=AdminUserResponse)
def create_user(
    payload: AdminUserCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminUserResponse:
    _require_admin_workspace(_admin, payload.workspace_id)
    workspace = _get_active_workspace_or_404(session, payload.workspace_id)
    user = User(
        workspace=workspace,
        external_id=payload.external_id,
        display_name=payload.display_name,
        status=payload.status,
    )
    session.add(user)
    _flush_or_conflict(session, "user_conflict", "User could not be created")
    _record_admin_audit_event(session, request, workspace_id=workspace.id, user_id=user.id)
    _commit_or_conflict(session, "user_conflict", "User could not be created")
    return AdminUserResponse(user=UserAdminSummary.model_validate(user))


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    include_disabled: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminUserListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    statement = select(User).order_by(User.external_id)
    if workspace_id is not None:
        statement = statement.where(User.workspace_id == workspace_id)
    if not include_disabled:
        statement = statement.where(User.status == ACTIVE_STATUS)
    users = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminUserListResponse(
        users=[UserAdminSummary.model_validate(user) for user in users],
        limit=limit,
        offset=offset,
    )


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user_status(
    user_id: UUID,
    payload: AdminLifecycleStatusUpdateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminUserResponse:
    user = _get_user_or_404(session, user_id)
    _require_admin_workspace(_admin, user.workspace_id)
    if payload.status == ACTIVE_STATUS:
        _get_active_workspace_or_404(session, user.workspace_id)
    user.status = payload.status
    _record_admin_audit_event(session, request, workspace_id=user.workspace_id, user_id=user.id)
    _commit_or_conflict(session, "user_conflict", "User could not be updated")
    return AdminUserResponse(user=UserAdminSummary.model_validate(user))


@router.post(
    "/capabilities",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminCapabilityResponse,
)
def create_capability(
    payload: AdminCapabilityCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminCapabilityResponse:
    _require_admin_workspace(_admin, payload.workspace_id)
    workspace = _get_active_workspace_or_404(session, payload.workspace_id)
    application = _get_active_application_or_404(session, payload.application_instance_id)
    if application.workspace_id != workspace.id:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "application_workspace_mismatch",
            "Application does not belong to the workspace",
        )
    if application.provider_type != payload.provider_type:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "application_provider_mismatch",
            "Application provider does not match the capability",
        )

    _check_capability_definition(payload)
    _check_no_raw_passthrough(payload.operation, payload.input_schema)

    capability = Capability(
        id=payload.id,
        workspace=workspace,
        application_instance=application,
        name=payload.name,
        version=payload.version,
        provider_type=payload.provider_type,
        adapter=payload.adapter,
        operation=payload.operation,
        auth_mode=payload.auth_mode,
        risk_class=payload.risk_class,
        input_schema=payload.input_schema,
        output_schema=payload.output_schema,
        status=payload.status,
    )
    session.add(capability)
    _flush_or_conflict(session, "capability_conflict", "Capability could not be created")
    _record_admin_audit_event(
        session,
        request,
        workspace_id=workspace.id,
        application_instance_id=application.id,
        capability_id=capability.id,
    )
    _commit_or_conflict(session, "capability_conflict", "Capability could not be created")
    return AdminCapabilityResponse(capability=CapabilityAdminSummary.model_validate(capability))


@router.get("/capability-templates", response_model=AdminCapabilityTemplateListResponse)
def list_admin_capability_templates(
    _admin: AdminBootstrap,
    provider_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminCapabilityTemplateListResponse:
    templates = list_capability_templates(provider_type)
    return AdminCapabilityTemplateListResponse(
        templates=[
            CapabilityTemplateAdminSummary(**template.as_dict())
            for template in templates[offset : offset + limit]
        ],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/capabilities/from-template",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminCapabilityResponse,
)
def create_capability_from_template(
    payload: AdminCapabilityFromTemplateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminCapabilityResponse:
    _require_admin_workspace(_admin, payload.workspace_id)
    template = get_capability_template(payload.template_id)
    if template is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "capability_template_not_found",
            "Capability template was not found",
        )
    workspace = _get_active_workspace_or_404(session, payload.workspace_id)
    application = _get_active_application_or_404(session, payload.application_instance_id)
    if application.workspace_id != workspace.id:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "application_workspace_mismatch",
            "Application does not belong to the workspace",
        )
    if application.provider_type != template.provider_type:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "application_provider_mismatch",
            "Application provider does not match the capability template",
        )

    template_data = template.as_dict()
    _check_capability_schema(template_data["input_schema"])
    _check_capability_schema(template_data["output_schema"])

    capability = Capability(
        id=payload.id or template.id,
        workspace=workspace,
        application_instance=application,
        name=payload.name or template.name,
        version=payload.version or template.version,
        provider_type=template.provider_type,
        adapter=template.adapter,
        operation=template.operation,
        auth_mode=template.auth_mode,
        risk_class=template.risk_class,
        input_schema=template_data["input_schema"],
        output_schema=template_data["output_schema"],
        status=payload.status,
    )
    session.add(capability)
    _flush_or_conflict(session, "capability_conflict", "Capability could not be created")
    _record_admin_audit_event(
        session,
        request,
        workspace_id=workspace.id,
        application_instance_id=application.id,
        capability_id=capability.id,
    )
    _commit_or_conflict(session, "capability_conflict", "Capability could not be created")
    return AdminCapabilityResponse(capability=CapabilityAdminSummary.model_validate(capability))


@router.get("/capabilities", response_model=AdminCapabilityListResponse)
def list_admin_capabilities(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    application_instance_id: UUID | None = None,
    include_disabled: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminCapabilityListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    statement = select(Capability).order_by(Capability.id)
    if workspace_id is not None:
        statement = statement.where(Capability.workspace_id == workspace_id)
    if application_instance_id is not None:
        statement = statement.where(Capability.application_instance_id == application_instance_id)
    if not include_disabled:
        statement = statement.where(Capability.status == ACTIVE_STATUS)
    capabilities = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminCapabilityListResponse(
        capabilities=[
            CapabilityAdminSummary.model_validate(capability) for capability in capabilities
        ],
        limit=limit,
        offset=offset,
    )


@router.patch("/capabilities/{capability_id}", response_model=AdminCapabilityResponse)
def update_capability_status(
    capability_id: str,
    payload: AdminLifecycleStatusUpdateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminCapabilityResponse:
    capability = _get_capability_or_404(session, capability_id)
    _require_admin_workspace(_admin, capability.workspace_id)
    if payload.status == ACTIVE_STATUS:
        workspace = _get_active_workspace_or_404(session, capability.workspace_id)
        application = _get_active_application_or_404(session, capability.application_instance_id)
        _require_same_workspace(
            application.workspace_id,
            workspace.id,
            "application_workspace_mismatch",
        )
    capability.status = payload.status
    _record_admin_audit_event(
        session,
        request,
        workspace_id=capability.workspace_id,
        capability_id=capability.id,
        application_instance_id=capability.application_instance_id,
    )
    _commit_or_conflict(session, "capability_conflict", "Capability could not be updated")
    return AdminCapabilityResponse(capability=CapabilityAdminSummary.model_validate(capability))


@router.post(
    "/permissions",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminPermissionResponse,
)
def create_permission(
    payload: AdminPermissionCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminPermissionResponse:
    _require_super_admin(_admin)
    permission = Permission(code=payload.code, description=payload.description)
    session.add(permission)
    _record_admin_audit_event(session, request, workspace_id=None)
    _commit_or_conflict(session, "permission_conflict", "Permission could not be created")
    return AdminPermissionResponse(permission=PermissionAdminSummary.model_validate(permission))


@router.get("/permissions", response_model=AdminPermissionListResponse)
def list_permissions(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminPermissionListResponse:
    if _ensure_default_permissions(session):
        session.commit()
    permissions = session.scalars(
        select(Permission).order_by(Permission.code).offset(offset).limit(limit)
    ).all()
    return AdminPermissionListResponse(
        permissions=[
            PermissionAdminSummary.model_validate(permission) for permission in permissions
        ],
        limit=limit,
        offset=offset,
    )


@router.post("/roles", status_code=status.HTTP_201_CREATED, response_model=AdminRoleResponse)
def create_role(
    payload: AdminRoleCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminRoleResponse:
    _require_admin_workspace(_admin, payload.workspace_id)
    workspace = _get_active_workspace_or_404(session, payload.workspace_id)
    if _ensure_default_permissions(session):
        _flush_or_conflict(session, "permission_conflict", "Permission could not be seeded")
    permission_codes = _dedupe_permission_codes(payload.permission_codes)
    missing_codes = _missing_permission_codes(session, permission_codes)
    if missing_codes:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "permission_unknown",
            "Role references an unknown permission",
        )

    role = Role(
        workspace=workspace,
        slug=payload.slug,
        display_name=payload.display_name,
        status=payload.status,
    )
    session.add(role)
    for permission_code in permission_codes:
        session.add(RolePermission(role=role, permission_code=permission_code))

    _flush_or_conflict(session, "role_conflict", "Role could not be created")
    _record_admin_audit_event(session, request, workspace_id=workspace.id)
    _commit_or_conflict(session, "role_conflict", "Role could not be created")
    return AdminRoleResponse(role=_role_summary(role, permission_codes))


@router.get("/roles", response_model=AdminRoleListResponse)
def list_roles(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    include_disabled: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminRoleListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    statement = select(Role).order_by(Role.slug)
    if workspace_id is not None:
        statement = statement.where(Role.workspace_id == workspace_id)
    if not include_disabled:
        statement = statement.where(Role.status == ACTIVE_STATUS)
    roles = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminRoleListResponse(
        roles=[_role_summary(role) for role in roles],
        limit=limit,
        offset=offset,
    )


@router.patch("/roles/{role_id}", response_model=AdminRoleResponse)
def update_role_status(
    role_id: UUID,
    payload: AdminLifecycleStatusUpdateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminRoleResponse:
    role = _get_role_or_404(session, role_id)
    _require_admin_workspace(_admin, role.workspace_id)
    if payload.status == ACTIVE_STATUS:
        _get_active_workspace_or_404(session, role.workspace_id)
    role.status = payload.status
    _record_admin_audit_event(session, request, workspace_id=role.workspace_id)
    _commit_or_conflict(session, "role_conflict", "Role could not be updated")
    return AdminRoleResponse(role=_role_summary(role))


@router.post(
    "/bindings",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminBindingResponse,
)
def create_binding(
    payload: AdminBindingCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminBindingResponse:
    _require_admin_workspace(_admin, payload.workspace_id)
    workspace = _get_active_workspace_or_404(session, payload.workspace_id)
    agent = _get_active_agent_or_404(session, payload.agent_id)
    user = _get_active_user_or_404(session, payload.user_id)
    capability = _get_active_capability_or_404(session, payload.capability_id)
    role = _get_active_role_or_404(session, payload.role_id)
    _require_same_workspace(agent.workspace_id, workspace.id, "agent_workspace_mismatch")
    _require_same_workspace(user.workspace_id, workspace.id, "user_workspace_mismatch")
    _require_same_workspace(capability.workspace_id, workspace.id, "capability_workspace_mismatch")
    _require_same_workspace(role.workspace_id, workspace.id, "role_workspace_mismatch")

    binding = Binding(
        workspace=workspace,
        agent=agent,
        user=user,
        capability=capability,
        role=role,
        status=payload.status,
    )
    session.add(binding)
    _flush_or_conflict(session, "binding_conflict", "Binding could not be created")
    _record_admin_audit_event(
        session,
        request,
        workspace_id=workspace.id,
        agent_id=agent.id,
        user_id=user.id,
        capability_id=capability.id,
        application_instance_id=capability.application_instance_id,
    )
    _commit_or_conflict(session, "binding_conflict", "Binding could not be created")
    return AdminBindingResponse(binding=BindingAdminSummary.model_validate(binding))


@router.get("/bindings", response_model=AdminBindingListResponse)
def list_bindings(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    actor_type: str | None = None,
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
    capability_id: str | None = None,
    role_id: UUID | None = None,
    include_disabled: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminBindingListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    statement = select(Binding).order_by(Binding.id)
    if workspace_id is not None:
        statement = statement.where(Binding.workspace_id == workspace_id)
    if agent_id is not None:
        statement = statement.where(Binding.agent_id == agent_id)
    if user_id is not None:
        statement = statement.where(Binding.user_id == user_id)
    if capability_id is not None:
        statement = statement.where(Binding.capability_id == capability_id)
    if role_id is not None:
        statement = statement.where(Binding.role_id == role_id)
    if not include_disabled:
        statement = statement.where(Binding.status == ACTIVE_STATUS)
    bindings = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminBindingListResponse(
        bindings=[BindingAdminSummary.model_validate(binding) for binding in bindings],
        limit=limit,
        offset=offset,
    )


@router.patch("/bindings/{binding_id}", response_model=AdminBindingResponse)
def update_binding_status(
    binding_id: UUID,
    payload: AdminLifecycleStatusUpdateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminBindingResponse:
    binding = _get_binding_or_404(session, binding_id)
    _require_admin_workspace(_admin, binding.workspace_id)
    if payload.status == ACTIVE_STATUS:
        _validate_binding_can_be_active(session, binding)
    binding.status = payload.status
    _record_admin_audit_event(
        session,
        request,
        workspace_id=binding.workspace_id,
        agent_id=binding.agent_id,
        user_id=binding.user_id,
        capability_id=binding.capability_id,
        application_instance_id=binding.capability.application_instance_id,
    )
    _commit_or_conflict(session, "binding_conflict", "Binding could not be updated")
    return AdminBindingResponse(binding=BindingAdminSummary.model_validate(binding))


@router.post("/secrets", status_code=status.HTTP_201_CREATED, response_model=AdminSecretResponse)
def create_secret(
    payload: AdminSecretCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminSecretResponse:
    _require_admin_workspace(_admin, payload.workspace_id)
    workspace = _get_active_workspace_or_404(session, payload.workspace_id)
    application = _get_active_application_or_404(session, payload.application_instance_id)
    if application.workspace_id != workspace.id:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "application_workspace_mismatch",
            "Application does not belong to the workspace",
        )
    _validate_secret_owner(session, workspace.id, payload.owner_type, payload.owner_id)
    try:
        encrypted_value = SecretCipher(request.app.state.settings.secret_encryption_key).encrypt(
            _secret_stored_value(payload.value, payload.external_reference)
        )
    except ValueError as exc:
        raise GrantoraAPIError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "secret_encryption_unavailable",
            "Secret encryption is unavailable",
        ) from exc

    secret = Secret(
        workspace=workspace,
        application_instance=application,
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        secret_type=payload.secret_type,
        encrypted_value=encrypted_value,
    )
    session.add(secret)
    _flush_or_conflict(session, "secret_conflict", "Secret could not be created")
    _record_admin_audit_event(
        session,
        request,
        workspace_id=workspace.id,
        agent_id=payload.owner_id if payload.owner_type == "agent" else None,
        user_id=payload.owner_id if payload.owner_type == "user" else None,
        application_instance_id=application.id,
    )
    _commit_or_conflict(session, "secret_conflict", "Secret could not be created")
    return AdminSecretResponse(secret=SecretAdminSummary.model_validate(secret))


@router.get("/secrets", response_model=AdminSecretListResponse)
def list_secrets(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    application_instance_id: UUID | None = None,
    owner_type: str | None = None,
    owner_id: UUID | None = None,
    include_revoked: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminSecretListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    statement = select(Secret).order_by(Secret.id)
    if workspace_id is not None:
        statement = statement.where(Secret.workspace_id == workspace_id)
    if application_instance_id is not None:
        statement = statement.where(Secret.application_instance_id == application_instance_id)
    if owner_type is not None:
        statement = statement.where(Secret.owner_type == owner_type)
    if owner_id is not None:
        statement = statement.where(Secret.owner_id == owner_id)
    if not include_revoked:
        statement = statement.where(Secret.status == ACTIVE_STATUS)
    secrets = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminSecretListResponse(
        secrets=[SecretAdminSummary.model_validate(secret) for secret in secrets],
        limit=limit,
        offset=offset,
    )


@router.patch("/secrets/{secret_id}", response_model=AdminSecretResponse)
def update_secret_status(
    secret_id: UUID,
    payload: AdminSecretStatusUpdateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminSecretResponse:
    secret = _get_secret_or_404(session, secret_id)
    _require_admin_workspace(_admin, secret.workspace_id)
    if payload.status == ACTIVE_STATUS:
        _validate_secret_can_be_active(session, secret)
    secret.status = payload.status
    _record_secret_admin_audit_event(session, request, secret)
    _commit_or_conflict(session, "secret_conflict", "Secret could not be updated")
    return AdminSecretResponse(secret=SecretAdminSummary.model_validate(secret))


@router.post("/secrets/{secret_id}/rotate", response_model=AdminSecretRotationResponse)
def rotate_secret(
    secret_id: UUID,
    payload: AdminSecretRotateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminSecretRotationResponse:
    old_secret = _get_active_secret_or_404(session, secret_id)
    _require_admin_workspace(_admin, old_secret.workspace_id)
    _validate_secret_can_be_active(session, old_secret)
    try:
        encrypted_value = SecretCipher(request.app.state.settings.secret_encryption_key).encrypt(
            _secret_stored_value(payload.value, payload.external_reference)
        )
    except ValueError as exc:
        raise GrantoraAPIError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "secret_encryption_unavailable",
            "Secret encryption is unavailable",
        ) from exc

    old_secret.status = REVOKED_STATUS
    replacement = Secret(
        workspace_id=old_secret.workspace_id,
        application_instance_id=old_secret.application_instance_id,
        owner_type=old_secret.owner_type,
        owner_id=old_secret.owner_id,
        secret_type=payload.secret_type or old_secret.secret_type,
        encrypted_value=encrypted_value,
        status=ACTIVE_STATUS,
    )
    session.add(replacement)
    _flush_or_conflict(session, "secret_conflict", "Secret could not be rotated")
    _record_secret_admin_audit_event(session, request, replacement)
    _commit_or_conflict(session, "secret_conflict", "Secret could not be rotated")
    return AdminSecretRotationResponse(
        secret=SecretAdminSummary.model_validate(replacement),
        revoked_secret=SecretAdminSummary.model_validate(old_secret),
    )


@router.get("/audit", response_model=AdminAuditListResponse)
def list_audit_events(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    actor_type: str | None = None,
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
    capability_id: str | None = None,
    decision: str | None = None,
    outcome: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminAuditListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    statement = _audit_statement(
        workspace_id=workspace_id,
        actor_type=actor_type,
        agent_id=agent_id,
        user_id=user_id,
        capability_id=capability_id,
        decision=decision,
        outcome=outcome,
        start_time=start_time,
        end_time=end_time,
    ).order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
    events = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminAuditListResponse(
        audit=[AuditEventAdminSummary.model_validate(event) for event in events],
        limit=limit,
        offset=offset,
    )


@router.get("/usage", response_model=AdminUsageListResponse)
def list_usage_events(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
    capability_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminUsageListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    filters = _usage_filters(
        workspace_id=workspace_id,
        agent_id=agent_id,
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
    usage = session.scalars(usage_statement).all()
    summaries = [
        UsageAggregateSummary(
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
    return AdminUsageListResponse(
        usage=[UsageEventAdminSummary.model_validate(event) for event in usage],
        summaries=summaries,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/agents",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminAgentCreateResponse,
)
def create_agent(
    payload: AdminAgentCreateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminAgentCreateResponse:
    _require_admin_workspace(_admin, payload.workspace_id)
    workspace = get_active_workspace_by_id(session, payload.workspace_id)
    if workspace is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            "Workspace was not found",
        )

    plaintext_token = create_agent_token()
    token_hash = hash_token(plaintext_token, request.app.state.settings.agent_token_pepper)
    agent = Agent(
        workspace=workspace,
        slug=payload.slug,
        display_name=payload.display_name,
        token_hash=token_hash,
        token_hash_algorithm=TOKEN_HASH_ALGORITHM,
    )
    session.add(agent)

    _flush_or_conflict(session, "agent_conflict", "Agent could not be created")
    _record_admin_audit_event(session, request, workspace_id=workspace.id, agent_id=agent.id)
    _commit_or_conflict(session, "agent_conflict", "Agent could not be created")

    return AdminAgentCreateResponse(
        agent=AgentAdminSummary.model_validate(agent),
        token=plaintext_token,
    )


@router.get("/agents", response_model=AdminAgentListResponse)
def list_agents(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
    include_disabled: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AdminAgentListResponse:
    workspace_id = _workspace_filter_for_admin(_admin, workspace_id)
    statement = select(Agent).order_by(Agent.slug)
    if workspace_id is not None:
        statement = statement.where(Agent.workspace_id == workspace_id)
    if not include_disabled:
        statement = statement.where(Agent.status == ACTIVE_STATUS)

    agents = session.scalars(statement.offset(offset).limit(limit)).all()
    return AdminAgentListResponse(
        agents=[AgentAdminSummary.model_validate(agent) for agent in agents],
        limit=limit,
        offset=offset,
    )


@router.post("/agents/{agent_id}/rotate-token", response_model=AdminAgentCreateResponse)
def rotate_agent_token(
    agent_id: UUID,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminAgentCreateResponse:
    agent = _get_agent_or_404(session, agent_id)
    _require_admin_workspace(_admin, agent.workspace_id)
    plaintext_token = create_agent_token()
    agent.token_hash = hash_token(plaintext_token, request.app.state.settings.agent_token_pepper)
    agent.token_hash_algorithm = TOKEN_HASH_ALGORITHM
    _record_admin_audit_event(session, request, workspace_id=agent.workspace_id, agent_id=agent.id)
    _commit_or_conflict(session, "agent_conflict", "Agent token could not be rotated")
    return AdminAgentCreateResponse(
        agent=AgentAdminSummary.model_validate(agent),
        token=plaintext_token,
    )


@router.patch("/agents/{agent_id}", response_model=AdminAgentResponse)
def update_agent_status(
    agent_id: UUID,
    payload: AdminAgentUpdateRequest,
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminAgentResponse:
    agent = _get_agent_or_404(session, agent_id)
    _require_admin_workspace(_admin, agent.workspace_id)
    if payload.status == ACTIVE_STATUS:
        _get_active_workspace_or_404(session, agent.workspace_id)
    agent.status = payload.status
    _record_admin_audit_event(session, request, workspace_id=agent.workspace_id, agent_id=agent.id)
    _commit_or_conflict(session, "agent_conflict", "Agent could not be updated")
    return AdminAgentResponse(agent=AgentAdminSummary.model_validate(agent))


@router.post("/apisix/sync", response_model=AdminApisixSyncResponse)
async def sync_apisix_routes(
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminApisixSyncResponse:
    _require_super_admin(_admin)
    settings = request.app.state.settings
    client_factory = _get_apisix_client_factory(request)
    async with client_factory(settings) as apisix_client:
        result = await reconcile_apisix_routes(session, settings, apisix_client)

    return _apisix_sync_response_from_result(get_request_id(request), result)


@router.get("/apisix/status", response_model=AdminApisixStatusResponse)
async def get_apisix_status(
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
    include_drift: bool = False,
) -> AdminApisixStatusResponse:
    _require_super_admin(_admin)
    sync_status = get_apisix_sync_status(session)
    route_drift = await _get_apisix_route_drift(request, session) if include_drift else None
    if sync_status is None:
        return AdminApisixStatusResponse(
            status="never_run",
            route_drift=route_drift or ApisixRouteDriftSummary(),
        )
    return _apisix_status_response_from_model(sync_status, route_drift=route_drift)


def _require_super_admin(admin: AdminPrincipal) -> None:
    if admin.is_super_admin:
        return
    raise GrantoraAPIError(
        status.HTTP_403_FORBIDDEN,
        "admin_scope_denied",
        "Admin is not allowed to manage this resource",
    )


def _require_admin_workspace(admin: AdminPrincipal, workspace_id: UUID) -> None:
    if admin.workspace_id is None or admin.workspace_id == workspace_id:
        return
    raise GrantoraAPIError(
        status.HTTP_403_FORBIDDEN,
        "admin_scope_denied",
        "Admin is not allowed to manage this workspace",
    )


def _workspace_filter_for_admin(
    admin: AdminPrincipal,
    requested_workspace_id: UUID | None,
) -> UUID | None:
    if admin.workspace_id is None:
        return requested_workspace_id
    if requested_workspace_id is not None and requested_workspace_id != admin.workspace_id:
        raise GrantoraAPIError(
            status.HTTP_403_FORBIDDEN,
            "admin_scope_denied",
            "Admin is not allowed to inspect this workspace",
        )
    return admin.workspace_id


def _flush_or_conflict(session: Session, code: str, message: str) -> None:
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise GrantoraAPIError(status.HTTP_409_CONFLICT, code, message) from exc


def _commit_or_conflict(session: Session, code: str, message: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise GrantoraAPIError(status.HTTP_409_CONFLICT, code, message) from exc


def _record_admin_audit_event(
    session: Session,
    request: Request,
    *,
    workspace_id: UUID | None,
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
    capability_id: str | None = None,
    application_instance_id: UUID | None = None,
) -> None:
    record_audit_event(
        session,
        request_id=get_request_id(request),
        actor_type=getattr(request.state, "admin_actor_type", "admin_bootstrap"),
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user_id,
        capability_id=capability_id,
        application_instance_id=application_instance_id,
        decision="allow",
        outcome="success",
        error_code=None,
        latency_ms=0,
        remote_addr=request.client.host if request.client else None,
    )


def _get_workspace_or_404(session: Session, workspace_id: UUID) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            "Workspace was not found",
        )
    return workspace


def _get_active_workspace_or_404(session: Session, workspace_id: UUID) -> Workspace:
    workspace = get_active_workspace_by_id(session, workspace_id)
    if workspace is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "workspace_not_found",
            "Workspace was not found",
        )
    return workspace


def _get_application_or_404(
    session: Session,
    application_id: UUID,
) -> ApplicationInstance:
    application = session.get(ApplicationInstance, application_id)
    if application is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "application_not_found",
            "Application was not found",
        )
    return application


def _get_active_application_or_404(
    session: Session,
    application_id: UUID,
) -> ApplicationInstance:
    application = session.get(ApplicationInstance, application_id)
    if application is None or application.status != ACTIVE_STATUS:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "application_not_found",
            "Application was not found",
        )
    return application


def _get_active_agent_or_404(session: Session, agent_id: UUID) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None or agent.status != ACTIVE_STATUS:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "agent_not_found",
            "Agent was not found",
        )
    return agent


def _get_active_user_or_404(session: Session, user_id: UUID) -> User:
    user = session.get(User, user_id)
    if user is None or user.status != ACTIVE_STATUS:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "user_not_found",
            "User was not found",
        )
    return user


def _get_active_capability_or_404(session: Session, capability_id: str) -> Capability:
    capability = session.get(Capability, capability_id)
    if capability is None or capability.status != ACTIVE_STATUS:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "capability_not_found",
            "Capability was not found",
        )
    return capability


def _get_active_role_or_404(session: Session, role_id: UUID) -> Role:
    role = session.get(Role, role_id)
    if role is None or role.status != ACTIVE_STATUS:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "role_not_found",
            "Role was not found",
        )
    return role


def _get_agent_or_404(session: Session, agent_id: UUID) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "agent_not_found",
            "Agent was not found",
        )
    return agent


def _get_user_or_404(session: Session, user_id: UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "user_not_found",
            "User was not found",
        )
    return user


def _get_capability_or_404(session: Session, capability_id: str) -> Capability:
    capability = session.get(Capability, capability_id)
    if capability is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "capability_not_found",
            "Capability was not found",
        )
    return capability


def _get_role_or_404(session: Session, role_id: UUID) -> Role:
    role = session.get(Role, role_id)
    if role is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "role_not_found",
            "Role was not found",
        )
    return role


def _get_binding_or_404(session: Session, binding_id: UUID) -> Binding:
    binding = session.get(Binding, binding_id)
    if binding is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "binding_not_found",
            "Binding was not found",
        )
    return binding


def _get_secret_or_404(session: Session, secret_id: UUID) -> Secret:
    secret = session.get(Secret, secret_id)
    if secret is None:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "secret_not_found",
            "Secret was not found",
        )
    return secret


def _get_active_secret_or_404(session: Session, secret_id: UUID) -> Secret:
    secret = _get_secret_or_404(session, secret_id)
    if secret.status != ACTIVE_STATUS:
        raise GrantoraAPIError(
            status.HTTP_404_NOT_FOUND,
            "secret_not_found",
            "Secret was not found",
        )
    return secret


def _require_same_workspace(
    actual_workspace_id: UUID, expected_workspace_id: UUID, code: str
) -> None:
    if actual_workspace_id != expected_workspace_id:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            code,
            "Referenced resource does not belong to the workspace",
        )


def _check_capability_schema(schema: dict[str, object]) -> None:
    try:
        check_json_schema(schema)
    except CapabilitySchemaValidationError as exc:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, exc.message
        ) from exc


def _check_capability_definition(payload: AdminCapabilityCreateRequest) -> None:
    try:
        validate_capability_definition(
            capability_id=payload.id,
            name=payload.name,
            provider_type=payload.provider_type,
            adapter=payload.adapter,
            operation=payload.operation,
            auth_mode=payload.auth_mode,
            risk_class=payload.risk_class,
            input_schema=payload.input_schema,
            output_schema=payload.output_schema,
        )
    except CapabilitySchemaValidationError as exc:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, exc.message
        ) from exc


def _check_no_raw_passthrough(operation: str, input_schema: dict[str, object]) -> None:
    properties = input_schema.get("properties", {})
    property_names = set(properties) if isinstance(properties, dict) else set()
    if (
        operation in RAW_PASSTHROUGH_OPERATIONS
        or operation.startswith("raw.")
        or "passthrough" in operation
        or RAW_PASSTHROUGH_INPUT_FIELDS.intersection(property_names)
    ):
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "raw_passthrough_unavailable",
            "Raw upstream passthrough capabilities are not available",
        )


def _ensure_default_permissions(session: Session) -> bool:
    permission_codes = set(DEFAULT_PERMISSION_DESCRIPTIONS)
    existing_codes = set(
        session.scalars(select(Permission.code).where(Permission.code.in_(permission_codes))).all()
    )
    missing_codes = sorted(permission_codes - existing_codes)
    for permission_code in missing_codes:
        session.add(
            Permission(
                code=permission_code,
                description=DEFAULT_PERMISSION_DESCRIPTIONS[permission_code],
            )
        )
    return bool(missing_codes)


def _dedupe_permission_codes(permission_codes: list[str]) -> list[str]:
    return list(dict.fromkeys(permission_codes))


def _missing_permission_codes(session: Session, permission_codes: list[str]) -> list[str]:
    if not permission_codes:
        return []
    existing_codes = set(
        session.scalars(select(Permission.code).where(Permission.code.in_(permission_codes))).all()
    )
    return sorted(set(permission_codes) - existing_codes)


def _role_summary(role: Role, permission_codes: list[str] | None = None) -> RoleAdminSummary:
    codes = permission_codes
    if codes is None:
        codes = sorted(role_permission.permission_code for role_permission in role.role_permissions)
    return RoleAdminSummary(
        id=role.id,
        workspace_id=role.workspace_id,
        slug=role.slug,
        display_name=role.display_name,
        permission_codes=codes,
        status=role.status,
    )


def _validate_secret_owner(
    session: Session,
    workspace_id: UUID,
    owner_type: str,
    owner_id: UUID,
) -> None:
    if owner_type == "workspace":
        if owner_id != workspace_id:
            raise GrantoraAPIError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "secret_owner_mismatch",
                "Secret owner does not belong to the workspace",
            )
        return
    if owner_type == "user":
        user = _get_active_user_or_404(session, owner_id)
        _require_same_workspace(user.workspace_id, workspace_id, "user_workspace_mismatch")
        return
    if owner_type == "agent":
        agent = _get_active_agent_or_404(session, owner_id)
        _require_same_workspace(agent.workspace_id, workspace_id, "agent_workspace_mismatch")
        return
    raise GrantoraAPIError(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "secret_owner_invalid",
        "Secret owner type is invalid",
    )


def _secret_stored_value(value: str | None, external_reference: str | None) -> str:
    if external_reference is not None:
        return stored_external_secret_reference(external_reference)
    if value is None:
        raise GrantoraAPIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "secret_value_invalid",
            "Secret value is invalid",
        )
    return value


def _validate_binding_can_be_active(session: Session, binding: Binding) -> None:
    workspace = _get_active_workspace_or_404(session, binding.workspace_id)
    agent = _get_active_agent_or_404(session, binding.agent_id)
    user = _get_active_user_or_404(session, binding.user_id)
    capability = _get_active_capability_or_404(session, binding.capability_id)
    role = _get_active_role_or_404(session, binding.role_id)
    _require_same_workspace(agent.workspace_id, workspace.id, "agent_workspace_mismatch")
    _require_same_workspace(user.workspace_id, workspace.id, "user_workspace_mismatch")
    _require_same_workspace(capability.workspace_id, workspace.id, "capability_workspace_mismatch")
    _require_same_workspace(role.workspace_id, workspace.id, "role_workspace_mismatch")


def _validate_secret_can_be_active(session: Session, secret: Secret) -> None:
    workspace = _get_active_workspace_or_404(session, secret.workspace_id)
    application = _get_active_application_or_404(session, secret.application_instance_id)
    _require_same_workspace(
        application.workspace_id,
        workspace.id,
        "application_workspace_mismatch",
    )
    _validate_secret_owner(session, workspace.id, secret.owner_type, secret.owner_id)


def _record_secret_admin_audit_event(
    session: Session,
    request: Request,
    secret: Secret,
) -> None:
    _record_admin_audit_event(
        session,
        request,
        workspace_id=secret.workspace_id,
        agent_id=secret.owner_id if secret.owner_type == "agent" else None,
        user_id=secret.owner_id if secret.owner_type == "user" else None,
        application_instance_id=secret.application_instance_id,
    )


def _audit_statement(
    *,
    workspace_id: UUID | None,
    actor_type: str | None,
    agent_id: UUID | None,
    user_id: UUID | None,
    capability_id: str | None,
    decision: str | None,
    outcome: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
):
    statement = select(AuditEvent)
    if workspace_id is not None:
        statement = statement.where(AuditEvent.workspace_id == workspace_id)
    if actor_type is not None:
        statement = statement.where(AuditEvent.actor_type == actor_type)
    if agent_id is not None:
        statement = statement.where(AuditEvent.agent_id == agent_id)
    if user_id is not None:
        statement = statement.where(AuditEvent.user_id == user_id)
    if capability_id is not None:
        statement = statement.where(AuditEvent.capability_id == capability_id)
    if decision is not None:
        statement = statement.where(AuditEvent.decision == decision)
    if outcome is not None:
        statement = statement.where(AuditEvent.outcome == outcome)
    if start_time is not None:
        statement = statement.where(AuditEvent.timestamp >= start_time)
    if end_time is not None:
        statement = statement.where(AuditEvent.timestamp <= end_time)
    return statement


def _usage_filters(
    *,
    workspace_id: UUID | None,
    agent_id: UUID | None,
    user_id: UUID | None,
    capability_id: str | None,
    status_filter: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
) -> list[object]:
    filters: list[object] = []
    if workspace_id is not None:
        filters.append(UsageEvent.workspace_id == workspace_id)
    if agent_id is not None:
        filters.append(UsageEvent.agent_id == agent_id)
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


def _get_apisix_client_factory(request: Request):
    return getattr(request.app.state, "apisix_client_factory", _create_apisix_admin_client)


def _create_apisix_admin_client(settings: Settings) -> ApisixAdminClient:
    return ApisixAdminClient(
        settings.apisix_admin_url,
        settings.apisix_admin_key,
        timeout_seconds=settings.apisix_admin_timeout_seconds,
    )


def _apisix_sync_response_from_result(
    request_id: str,
    result: ApisixSyncResult,
) -> AdminApisixSyncResponse:
    return AdminApisixSyncResponse(
        request_id=request_id,
        status=result.status,
        checked_routes=result.checked_routes,
        changed_routes=result.changed_routes,
        error=_apisix_error_summary(result.error_code, result.safe_message),
    )


def _apisix_status_response_from_model(
    sync_status: ApisixSyncStatus,
    *,
    route_drift: ApisixRouteDriftSummary | None = None,
) -> AdminApisixStatusResponse:
    return AdminApisixStatusResponse(
        status=sync_status.status,
        last_started_at=sync_status.last_started_at,
        last_finished_at=sync_status.last_finished_at,
        checked_routes=sync_status.checked_routes,
        changed_routes=sync_status.changed_routes,
        error=_apisix_error_summary(sync_status.error_code, sync_status.safe_message),
        route_drift=route_drift or ApisixRouteDriftSummary(),
    )


async def _get_apisix_route_drift(
    request: Request,
    session: Session,
) -> ApisixRouteDriftSummary:
    settings = request.app.state.settings
    client_factory = _get_apisix_client_factory(request)
    async with client_factory(settings) as apisix_client:
        result = await check_apisix_route_drift(session, settings, apisix_client)
    return _apisix_route_drift_response_from_result(result)


def _apisix_route_drift_response_from_result(
    result: ApisixRouteDriftResult,
) -> ApisixRouteDriftSummary:
    return ApisixRouteDriftSummary(
        status=result.status,
        checked_routes=result.checked_routes,
        drifted_routes=result.drifted_routes,
        missing_routes=result.missing_routes,
        error=_apisix_error_summary(result.error_code, result.safe_message),
    )


def _apisix_error_summary(
    code: str | None,
    message: str | None,
) -> ApisixSyncErrorSummary | None:
    if code is None:
        return None
    return ApisixSyncErrorSummary(code=code, message=message or "APISIX sync failed")
