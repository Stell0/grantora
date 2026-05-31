from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

LifecycleStatus = Literal["active", "disabled"]
SecretStatus = Literal["active", "revoked"]
OwnerType = Literal["workspace", "user", "agent"]
SecretType = Literal[
    "api_key", "bearer_token", "basic_auth", "oauth_refresh_token", "session_cookie"
]
AuthMode = Literal["system", "user", "user+scope", "admin"]
RiskClass = Literal["read_only", "draft", "side_effect", "destructive", "admin"]


class WorkspaceAdminSummary(BaseModel):
    id: UUID
    slug: str
    display_name: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class AdminWorkspaceCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    status: LifecycleStatus = "active"


class AdminWorkspaceResponse(BaseModel):
    workspace: WorkspaceAdminSummary


class AdminWorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceAdminSummary]


class ApplicationAdminSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    slug: str
    display_name: str
    provider_type: str
    base_url: str | None
    status: str

    model_config = ConfigDict(from_attributes=True)


class AdminApplicationCreateRequest(BaseModel):
    workspace_id: UUID
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    provider_type: str = Field(min_length=1, max_length=64)
    base_url: str | None = Field(default=None, max_length=2048)
    status: LifecycleStatus = "active"


class AdminApplicationResponse(BaseModel):
    application: ApplicationAdminSummary


class AdminApplicationListResponse(BaseModel):
    applications: list[ApplicationAdminSummary]


class UserAdminSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    external_id: str
    display_name: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class AdminUserCreateRequest(BaseModel):
    workspace_id: UUID
    external_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    status: LifecycleStatus = "active"


class AdminUserResponse(BaseModel):
    user: UserAdminSummary


class AdminUserListResponse(BaseModel):
    users: list[UserAdminSummary]


class CapabilityAdminSummary(BaseModel):
    id: str
    workspace_id: UUID
    application_instance_id: UUID
    name: str
    version: int
    provider_type: str
    adapter: str
    operation: str
    auth_mode: str
    risk_class: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: str

    model_config = ConfigDict(from_attributes=True)


class AdminCapabilityCreateRequest(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    workspace_id: UUID
    application_instance_id: UUID
    name: str = Field(min_length=1, max_length=255)
    version: int = Field(default=1, ge=1)
    provider_type: str = Field(min_length=1, max_length=64)
    adapter: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=128)
    auth_mode: AuthMode
    risk_class: RiskClass
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: LifecycleStatus = "active"


class AdminCapabilityResponse(BaseModel):
    capability: CapabilityAdminSummary


class AdminCapabilityListResponse(BaseModel):
    capabilities: list[CapabilityAdminSummary]


class PermissionAdminSummary(BaseModel):
    code: str
    description: str | None

    model_config = ConfigDict(from_attributes=True)


class AdminPermissionCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=255)


class AdminPermissionResponse(BaseModel):
    permission: PermissionAdminSummary


class AdminPermissionListResponse(BaseModel):
    permissions: list[PermissionAdminSummary]


class RoleAdminSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    slug: str
    display_name: str
    permission_codes: list[str]
    status: str


class AdminRoleCreateRequest(BaseModel):
    workspace_id: UUID
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    permission_codes: list[str] = Field(default_factory=list)
    status: LifecycleStatus = "active"


class AdminRoleResponse(BaseModel):
    role: RoleAdminSummary


class AdminRoleListResponse(BaseModel):
    roles: list[RoleAdminSummary]


class BindingAdminSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    agent_id: UUID
    user_id: UUID
    capability_id: str
    role_id: UUID
    status: str

    model_config = ConfigDict(from_attributes=True)


class AdminBindingCreateRequest(BaseModel):
    workspace_id: UUID
    agent_id: UUID
    user_id: UUID
    capability_id: str = Field(min_length=1, max_length=128)
    role_id: UUID
    status: LifecycleStatus = "active"


class AdminBindingResponse(BaseModel):
    binding: BindingAdminSummary


class AdminBindingListResponse(BaseModel):
    bindings: list[BindingAdminSummary]


class SecretAdminSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    application_instance_id: UUID
    owner_type: str
    owner_id: UUID
    secret_type: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class AdminSecretCreateRequest(BaseModel):
    workspace_id: UUID
    application_instance_id: UUID
    owner_type: OwnerType
    owner_id: UUID
    secret_type: SecretType
    value: str = Field(min_length=1)


class AdminSecretResponse(BaseModel):
    secret: SecretAdminSummary


class AdminSecretListResponse(BaseModel):
    secrets: list[SecretAdminSummary]


class AuditEventAdminSummary(BaseModel):
    id: UUID
    timestamp: datetime
    request_id: str
    actor_type: str
    workspace_id: UUID
    agent_id: UUID | None
    user_id: UUID | None
    capability_id: str | None
    application_instance_id: UUID | None
    decision: str
    outcome: str
    error_code: str | None
    latency_ms: int
    remote_addr: str | None

    model_config = ConfigDict(from_attributes=True)


class AdminAuditListResponse(BaseModel):
    audit: list[AuditEventAdminSummary]
    limit: int
    offset: int


class UsageEventAdminSummary(BaseModel):
    id: UUID
    timestamp: datetime
    workspace_id: UUID
    agent_id: UUID
    user_id: UUID | None
    capability_id: str
    application_instance_id: UUID | None
    units: int
    status: str
    latency_ms: int

    model_config = ConfigDict(from_attributes=True)


class UsageAggregateSummary(BaseModel):
    workspace_id: UUID
    agent_id: UUID
    user_id: UUID | None
    capability_id: str
    status: str
    events: int
    total_units: int


class AdminUsageListResponse(BaseModel):
    usage: list[UsageEventAdminSummary]
    summaries: list[UsageAggregateSummary]
    limit: int
    offset: int
