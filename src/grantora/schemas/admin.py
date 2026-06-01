from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from grantora.schemas.validation import (
    AdapterId,
    CapabilityId,
    ExternalId,
    OperationId,
    PermissionCode,
    ProviderType,
    Slug,
    UpstreamBaseURL,
)

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
    slug: Slug
    display_name: str = Field(min_length=1, max_length=255)
    status: LifecycleStatus = "active"


class AdminWorkspaceResponse(BaseModel):
    workspace: WorkspaceAdminSummary


class AdminWorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceAdminSummary]
    limit: int
    offset: int


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
    slug: Slug
    display_name: str = Field(min_length=1, max_length=255)
    provider_type: ProviderType
    base_url: UpstreamBaseURL | None = None
    status: LifecycleStatus = "active"


class AdminApplicationResponse(BaseModel):
    application: ApplicationAdminSummary


class AdminApplicationListResponse(BaseModel):
    applications: list[ApplicationAdminSummary]
    limit: int
    offset: int


class UserAdminSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    external_id: str
    display_name: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class AdminUserCreateRequest(BaseModel):
    workspace_id: UUID
    external_id: ExternalId
    display_name: str = Field(min_length=1, max_length=255)
    status: LifecycleStatus = "active"


class AdminUserResponse(BaseModel):
    user: UserAdminSummary


class AdminUserListResponse(BaseModel):
    users: list[UserAdminSummary]
    limit: int
    offset: int


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
    model_config = ConfigDict(extra="forbid")

    id: CapabilityId
    workspace_id: UUID
    application_instance_id: UUID
    name: str = Field(min_length=1, max_length=255)
    version: int = Field(default=1, ge=1)
    provider_type: ProviderType
    adapter: AdapterId
    operation: OperationId
    auth_mode: AuthMode
    risk_class: RiskClass
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: LifecycleStatus = "active"


class AdminCapabilityResponse(BaseModel):
    capability: CapabilityAdminSummary


class AdminCapabilityListResponse(BaseModel):
    capabilities: list[CapabilityAdminSummary]
    limit: int
    offset: int


class CapabilityTemplateAdminSummary(BaseModel):
    id: str
    name: str
    version: int
    provider_type: str
    adapter: str
    operation: str
    auth_mode: str
    risk_class: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_secret_types: list[str]
    upstream_permissions: list[str]


class AdminCapabilityTemplateListResponse(BaseModel):
    templates: list[CapabilityTemplateAdminSummary]
    limit: int
    offset: int


class AdminCapabilityFromTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: CapabilityId
    workspace_id: UUID
    application_instance_id: UUID
    id: CapabilityId | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    version: int | None = Field(default=None, ge=1)
    status: LifecycleStatus = "active"


class PermissionAdminSummary(BaseModel):
    code: str
    description: str | None

    model_config = ConfigDict(from_attributes=True)


class AdminPermissionCreateRequest(BaseModel):
    code: PermissionCode
    description: str | None = Field(default=None, max_length=255)


class AdminPermissionResponse(BaseModel):
    permission: PermissionAdminSummary


class AdminPermissionListResponse(BaseModel):
    permissions: list[PermissionAdminSummary]
    limit: int
    offset: int


class RoleAdminSummary(BaseModel):
    id: UUID
    workspace_id: UUID
    slug: str
    display_name: str
    permission_codes: list[str]
    status: str


class AdminRoleCreateRequest(BaseModel):
    workspace_id: UUID
    slug: Slug
    display_name: str = Field(min_length=1, max_length=255)
    permission_codes: list[PermissionCode] = Field(default_factory=list)
    status: LifecycleStatus = "active"


class AdminRoleResponse(BaseModel):
    role: RoleAdminSummary


class AdminRoleListResponse(BaseModel):
    roles: list[RoleAdminSummary]
    limit: int
    offset: int


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
    capability_id: CapabilityId
    role_id: UUID
    status: LifecycleStatus = "active"


class AdminBindingResponse(BaseModel):
    binding: BindingAdminSummary


class AdminBindingListResponse(BaseModel):
    bindings: list[BindingAdminSummary]
    limit: int
    offset: int


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
    value: str | None = Field(default=None, min_length=1)
    external_reference: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def require_one_secret_source(self) -> AdminSecretCreateRequest:
        if (self.value is None) == (self.external_reference is None):
            raise ValueError("provide exactly one of value or external_reference")
        return self


class AdminLifecycleStatusUpdateRequest(BaseModel):
    status: LifecycleStatus


class AdminSecretStatusUpdateRequest(BaseModel):
    status: SecretStatus


class AdminSecretRotateRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1)
    external_reference: str | None = Field(default=None, min_length=1, max_length=512)
    secret_type: SecretType | None = None

    @model_validator(mode="after")
    def require_one_secret_source(self) -> AdminSecretRotateRequest:
        if (self.value is None) == (self.external_reference is None):
            raise ValueError("provide exactly one of value or external_reference")
        return self


class AdminSecretResponse(BaseModel):
    secret: SecretAdminSummary


class AdminSecretRotationResponse(BaseModel):
    secret: SecretAdminSummary
    revoked_secret: SecretAdminSummary


class AdminSecretListResponse(BaseModel):
    secrets: list[SecretAdminSummary]
    limit: int
    offset: int


class AuditEventAdminSummary(BaseModel):
    id: UUID
    timestamp: datetime
    request_id: str
    actor_type: str
    workspace_id: UUID | None
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
