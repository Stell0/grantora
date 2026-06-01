from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates
from sqlalchemy.types import JSON, TypeDecorator, Uuid

from grantora.capabilities.validation import check_json_schema

ACTIVE_STATUS = "active"
REVOKED_STATUS = "revoked"

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def empty_object_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False}


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("status in ('active', 'disabled')", name="ck_workspaces_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    application_instances: Mapped[list[ApplicationInstance]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    agents: Mapped[list[Agent]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    users: Mapped[list[User]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    capabilities: Mapped[list[Capability]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    roles: Mapped[list[Role]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    bindings: Mapped[list[Binding]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    secrets: Mapped[list[Secret]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    usage_events: Mapped[list[UsageEvent]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    admin_credentials: Mapped[list[AdminCredential]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class AdminCredential(TimestampMixin, Base):
    __tablename__ = "admin_credentials"
    __table_args__ = (
        UniqueConstraint("subject", name="uq_admin_credentials_subject"),
        UniqueConstraint("token_hash", name="uq_admin_credentials_token_hash"),
        Index("idx_admin_credentials_token_hash_status", "token_hash", "status"),
        Index("idx_admin_credentials_workspace_status", "workspace_id", "status"),
        CheckConstraint("status in ('active', 'disabled')", name="ck_admin_credentials_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash_algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
    )
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace | None] = relationship(back_populates="admin_credentials")


class ApplicationInstance(TimestampMixin, Base):
    __tablename__ = "application_instances"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_application_instances_workspace_slug"),
        Index("idx_application_instances_workspace_slug", "workspace_id", "slug", "status"),
        CheckConstraint(
            "status in ('active', 'disabled')",
            name="ck_application_instances_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="application_instances")
    capabilities: Mapped[list[Capability]] = relationship(
        back_populates="application_instance",
        cascade="all, delete-orphan",
    )
    secrets: Mapped[list[Secret]] = relationship(
        back_populates="application_instance",
        cascade="all, delete-orphan",
    )


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),
        Index("idx_agents_token_hash_status", "token_hash", "status"),
        CheckConstraint("status in ('active', 'disabled')", name="ck_agents_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    token_hash_algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="agents")
    bindings: Mapped[list[Binding]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="agent")
    usage_events: Mapped[list[UsageEvent]] = relationship(back_populates="agent")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_users_workspace_external_id"),
        Index("idx_users_workspace_external_status", "workspace_id", "external_id", "status"),
        CheckConstraint("status in ('active', 'disabled')", name="ck_users_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="users")
    bindings: Mapped[list[Binding]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="user")
    usage_events: Mapped[list[UsageEvent]] = relationship(back_populates="user")


class Capability(TimestampMixin, Base):
    __tablename__ = "capabilities"
    __table_args__ = (
        Index("idx_capabilities_workspace_status", "workspace_id", "status"),
        CheckConstraint("version >= 1", name="ck_capabilities_version_positive"),
        CheckConstraint("status in ('active', 'disabled')", name="ck_capabilities_status"),
        CheckConstraint(
            "auth_mode in ('system', 'user', 'user+scope', 'admin')",
            name="ck_capabilities_auth_mode",
        ),
        CheckConstraint(
            "risk_class in ('read_only', 'draft', 'side_effect', 'destructive', 'admin')",
            name="ck_capabilities_risk_class",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    application_instance_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("application_instances.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_class: Mapped[str] = mapped_column(String(32), nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=empty_object_schema
    )
    output_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=empty_object_schema
    )
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="capabilities")
    application_instance: Mapped[ApplicationInstance] = relationship(back_populates="capabilities")
    bindings: Mapped[list[Binding]] = relationship(
        back_populates="capability",
        cascade="all, delete-orphan",
    )

    @validates("input_schema", "output_schema")
    def validate_schema(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        check_json_schema(value)
        return value


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_roles_workspace_slug"),
        Index("idx_roles_workspace_slug_status", "workspace_id", "slug", "status"),
        CheckConstraint("status in ('active', 'disabled')", name="ck_roles_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="roles")
    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
    )
    bindings: Mapped[list[Binding]] = relationship(back_populates="role")


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str | None] = mapped_column(String(255))

    role_permissions: Mapped[list[RolePermission]] = relationship(
        back_populates="permission",
        cascade="all, delete-orphan",
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("roles.id"),
        primary_key=True,
    )
    permission_code: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("permissions.code"),
        primary_key=True,
    )

    role: Mapped[Role] = relationship(back_populates="role_permissions")
    permission: Mapped[Permission] = relationship(back_populates="role_permissions")


class Binding(Base):
    __tablename__ = "bindings"
    __table_args__ = (
        Index(
            "uq_bindings_active_lookup",
            "workspace_id",
            "agent_id",
            "user_id",
            "capability_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "idx_bindings_lookup", "workspace_id", "agent_id", "user_id", "capability_id", "status"
        ),
        CheckConstraint("status in ('active', 'disabled')", name="ck_bindings_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    capability_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("capabilities.id"),
        nullable=False,
    )
    role_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="bindings")
    agent: Mapped[Agent] = relationship(back_populates="bindings")
    user: Mapped[User] = relationship(back_populates="bindings")
    capability: Mapped[Capability] = relationship(back_populates="bindings")
    role: Mapped[Role] = relationship(back_populates="bindings")


class Secret(Base):
    __tablename__ = "secrets"
    __table_args__ = (
        Index(
            "uq_secrets_active_owner",
            "workspace_id",
            "application_instance_id",
            "owner_type",
            "owner_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "idx_secrets_lookup",
            "workspace_id",
            "application_instance_id",
            "owner_type",
            "owner_id",
            "status",
        ),
        CheckConstraint(
            "owner_type in ('workspace', 'user', 'agent')",
            name="ck_secrets_owner_type",
        ),
        CheckConstraint(
            "secret_type in "
            "('api_key', 'bearer_token', 'basic_auth', 'oauth_refresh_token', 'session_cookie')",
            name="ck_secrets_secret_type",
        ),
        CheckConstraint("status in ('active', 'revoked')", name="ck_secrets_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    application_instance_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("application_instances.id"),
        nullable=False,
    )
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    secret_type: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False, deferred=True)
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="secrets")
    application_instance: Mapped[ApplicationInstance] = relationship(back_populates="secrets")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("idx_audit_workspace_time", "workspace_id", "timestamp"),
        CheckConstraint(
            "actor_type in ('agent', 'admin_bootstrap', 'admin_token', 'admin_oidc')",
            name="ck_audit_events_actor_type",
        ),
        CheckConstraint("decision in ('allow', 'deny')", name="ck_audit_events_decision"),
        CheckConstraint("outcome in ('success', 'error')", name="ck_audit_events_outcome"),
        CheckConstraint("latency_ms >= 0", name="ck_audit_events_latency_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), default="agent", nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=True,
    )
    agent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"))
    user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    capability_id: Mapped[str | None] = mapped_column(String(128))
    application_instance_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("application_instances.id"),
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    remote_addr: Mapped[str | None] = mapped_column(String(64))

    workspace: Mapped[Workspace] = relationship(back_populates="audit_events")
    agent: Mapped[Agent | None] = relationship(back_populates="audit_events")
    user: Mapped[User | None] = relationship(back_populates="audit_events")
    application_instance: Mapped[ApplicationInstance | None] = relationship()


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("idx_usage_workspace_time", "workspace_id", "timestamp"),
        CheckConstraint("units > 0", name="ck_usage_events_units_positive"),
        CheckConstraint("status in ('success', 'error', 'denied')", name="ck_usage_events_status"),
        CheckConstraint("latency_ms >= 0", name="ck_usage_events_latency_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    capability_id: Mapped[str] = mapped_column(String(128), nullable=False)
    application_instance_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("application_instances.id"),
    )
    units: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="usage_events")
    agent: Mapped[Agent] = relationship(back_populates="usage_events")
    user: Mapped[User | None] = relationship(back_populates="usage_events")
    application_instance: Mapped[ApplicationInstance | None] = relationship()


class ApisixRoute(Base):
    __tablename__ = "apisix_routes"
    __table_args__ = (
        Index("idx_apisix_routes_status", "status"),
        CheckConstraint("status in ('active', 'disabled')", name="ck_apisix_routes_status"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    upstream: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    plugins: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )


class ApisixSyncStatus(Base):
    __tablename__ = "apisix_sync_status"
    __table_args__ = (
        CheckConstraint("status in ('ok', 'error')", name="ck_apisix_sync_status_status"),
        CheckConstraint("checked_routes >= 0", name="ck_apisix_sync_checked_nonnegative"),
        CheckConstraint("changed_routes >= 0", name="ck_apisix_sync_changed_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    checked_routes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changed_routes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    safe_message: Mapped[str | None] = mapped_column(String(255))
