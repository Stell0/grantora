from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

ACTIVE_STATUS = "active"
REVOKED_STATUS = "revoked"

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"

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


class ApplicationInstance(Base):
    __tablename__ = "application_instances"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_application_instances_workspace_slug"),
        Index("idx_application_instances_workspace_slug", "workspace_id", "slug", "status"),
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


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),
        Index("idx_agents_token_hash_status", "token_hash", "status"),
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


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_users_workspace_external_id"),
        Index("idx_users_workspace_external_status", "workspace_id", "external_id", "status"),
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


class Capability(Base):
    __tablename__ = "capabilities"
    __table_args__ = (Index("idx_capabilities_workspace_status", "workspace_id", "status"),)

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
        JSON_DOCUMENT, nullable=False, default=dict
    )
    output_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(String(32), default=ACTIVE_STATUS, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="capabilities")
    application_instance: Mapped[ApplicationInstance] = relationship(back_populates="capabilities")
    bindings: Mapped[list[Binding]] = relationship(
        back_populates="capability",
        cascade="all, delete-orphan",
    )


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_roles_workspace_slug"),
        Index("idx_roles_workspace_slug_status", "workspace_id", "slug", "status"),
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


class Permission(Base):
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
            "idx_bindings_lookup", "workspace_id", "agent_id", "user_id", "capability_id", "status"
        ),
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
            "idx_secrets_lookup",
            "workspace_id",
            "application_instance_id",
            "owner_type",
            "owner_id",
            "status",
        ),
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
    __table_args__ = (Index("idx_audit_workspace_time", "workspace_id", "timestamp"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id"),
        nullable=False,
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
    __table_args__ = (Index("idx_usage_workspace_time", "workspace_id", "timestamp"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
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
