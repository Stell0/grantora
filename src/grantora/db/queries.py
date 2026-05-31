from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from grantora.db.models import (
    ACTIVE_STATUS,
    Agent,
    ApplicationInstance,
    Binding,
    Capability,
    Role,
    RolePermission,
    User,
    Workspace,
)


def get_active_workspace_by_slug(session: Session, slug: str) -> Workspace | None:
    statement = select(Workspace).where(
        Workspace.slug == slug,
        Workspace.status == ACTIVE_STATUS,
    )
    return session.scalar(statement)


def get_active_workspace_by_id(session: Session, workspace_id: UUID) -> Workspace | None:
    statement = select(Workspace).where(
        Workspace.id == workspace_id,
        Workspace.status == ACTIVE_STATUS,
    )
    return session.scalar(statement)


def get_active_application_instance_by_slug(
    session: Session,
    workspace_id: UUID,
    slug: str,
) -> ApplicationInstance | None:
    statement = (
        select(ApplicationInstance)
        .join(ApplicationInstance.workspace)
        .where(
            ApplicationInstance.workspace_id == workspace_id,
            ApplicationInstance.slug == slug,
            ApplicationInstance.status == ACTIVE_STATUS,
            Workspace.status == ACTIVE_STATUS,
        )
    )
    return session.scalar(statement)


def get_active_agent_by_token_hash(session: Session, token_hash: str) -> Agent | None:
    statement = (
        select(Agent)
        .join(Agent.workspace)
        .where(
            Agent.token_hash == token_hash,
            Agent.status == ACTIVE_STATUS,
            Workspace.status == ACTIVE_STATUS,
        )
    )
    return session.scalar(statement)


def get_active_user_by_external_id(
    session: Session,
    workspace_id: UUID,
    external_id: str,
) -> User | None:
    statement = (
        select(User)
        .join(User.workspace)
        .where(
            User.workspace_id == workspace_id,
            User.external_id == external_id,
            User.status == ACTIVE_STATUS,
            Workspace.status == ACTIVE_STATUS,
        )
    )
    return session.scalar(statement)


def get_active_capability_by_id(
    session: Session,
    workspace_id: UUID,
    capability_id: str,
) -> Capability | None:
    statement = (
        select(Capability)
        .join(Capability.workspace)
        .where(
            Capability.workspace_id == workspace_id,
            Capability.id == capability_id,
            Capability.status == ACTIVE_STATUS,
            Workspace.status == ACTIVE_STATUS,
        )
    )
    return session.scalar(statement)


def role_grants_permission(session: Session, role_id: UUID, permission_code: str) -> bool:
    statement = (
        select(RolePermission)
        .join(RolePermission.role)
        .where(
            RolePermission.role_id == role_id,
            RolePermission.permission_code == permission_code,
            Role.status == ACTIVE_STATUS,
        )
    )
    return session.scalar(statement) is not None


def get_active_binding(
    session: Session,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID,
    capability_id: str,
) -> Binding | None:
    statement = select(Binding).where(
        Binding.workspace_id == workspace_id,
        Binding.agent_id == agent_id,
        Binding.user_id == user_id,
        Binding.capability_id == capability_id,
        Binding.status == ACTIVE_STATUS,
    )
    return session.scalar(statement)
