from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, undefer

from grantora.db.models import (
    ACTIVE_STATUS,
    AdminCredential,
    Agent,
    ApplicationInstance,
    Binding,
    Capability,
    Role,
    RolePermission,
    Secret,
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


def get_active_admin_credential_by_token_hash(
    session: Session,
    token_hash: str,
) -> AdminCredential | None:
    statement = (
        select(AdminCredential)
        .outerjoin(AdminCredential.workspace)
        .where(
            AdminCredential.token_hash == token_hash,
            AdminCredential.status == ACTIVE_STATUS,
            or_(AdminCredential.workspace_id.is_(None), Workspace.status == ACTIVE_STATUS),
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


def list_active_capabilities_for_agent_user(
    session: Session,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID,
) -> list[Capability]:
    statement = (
        select(Capability)
        .join(Binding, Binding.capability_id == Capability.id)
        .where(
            Capability.workspace_id == workspace_id,
            Capability.status == ACTIVE_STATUS,
            Binding.workspace_id == workspace_id,
            Binding.agent_id == agent_id,
            Binding.user_id == user_id,
            Binding.status == ACTIVE_STATUS,
        )
        .order_by(Capability.id)
    )
    return list(session.scalars(statement).all())


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


def get_active_secret_for_owner(
    session: Session,
    workspace_id: UUID,
    application_instance_id: UUID,
    owner_type: str,
    owner_id: UUID,
) -> Secret | None:
    statement = (
        select(Secret)
        .options(undefer(Secret.encrypted_value))
        .where(
            Secret.workspace_id == workspace_id,
            Secret.application_instance_id == application_instance_id,
            Secret.owner_type == owner_type,
            Secret.owner_id == owner_id,
            Secret.status == ACTIVE_STATUS,
        )
        .order_by(Secret.id)
    )
    return session.scalar(statement)
