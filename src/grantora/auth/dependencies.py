from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request, status
from sqlalchemy.orm import Session

from grantora.api.errors import GrantoraAPIError
from grantora.auth.tokens import hash_token, verify_token
from grantora.db.models import Agent
from grantora.db.queries import (
    get_active_admin_credential_by_token_hash,
    get_active_agent_by_token_hash,
)

AUTHENTICATE_HEADER = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class AdminPrincipal:
    actor_type: str
    subject: str
    workspace_id: UUID | None = None

    @property
    def is_super_admin(self) -> bool:
        return self.workspace_id is None


def get_database_session(request: Request) -> Iterator[Session]:
    yield from request.app.state.database.session()


DatabaseSession = Annotated[Session, Depends(get_database_session)]


def require_authenticated_agent(
    request: Request,
    session: DatabaseSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Agent:
    token = extract_bearer_token(
        authorization,
        missing_code="agent_auth_missing",
        invalid_code="agent_auth_invalid",
        invalid_message="Invalid agent token",
    )
    settings = request.app.state.settings

    try:
        token_hash = hash_token(token, settings.agent_token_pepper)
    except ValueError as exc:
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            "agent_auth_invalid",
            "Invalid agent token",
            AUTHENTICATE_HEADER,
        ) from exc

    agent = get_active_agent_by_token_hash(session, token_hash)
    if agent is None:
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            "agent_auth_invalid",
            "Invalid agent token",
            AUTHENTICATE_HEADER,
        )

    return agent


def require_admin_bootstrap(
    request: Request,
    session: DatabaseSession,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> AdminPrincipal:
    oidc_principal = _oidc_admin_principal(request)
    if oidc_principal is not None:
        _store_admin_principal(request, oidc_principal)
        return oidc_principal

    token = extract_bearer_token(
        authorization,
        missing_code="admin_auth_missing",
        invalid_code="admin_auth_invalid",
        invalid_message="Invalid admin token",
    )
    settings = request.app.state.settings

    try:
        token_hash = hash_token(token, settings.agent_token_pepper)
    except ValueError as exc:
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            "admin_auth_invalid",
            "Invalid admin token",
            AUTHENTICATE_HEADER,
        ) from exc

    if settings.admin_bootstrap_token_hash and verify_token(
        token,
        settings.admin_bootstrap_token_hash,
        settings.agent_token_pepper,
    ):
        principal = AdminPrincipal(actor_type="admin_bootstrap", subject="bootstrap")
        _store_admin_principal(request, principal)
        return principal

    admin_credential = get_active_admin_credential_by_token_hash(session, token_hash)
    if admin_credential is not None:
        principal = AdminPrincipal(
            actor_type="admin_token",
            subject=admin_credential.subject,
            workspace_id=admin_credential.workspace_id,
        )
        _store_admin_principal(request, principal)
        return principal

    if not settings.admin_bootstrap_token_hash:
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            "admin_auth_unavailable",
            "Admin authentication is not configured",
            AUTHENTICATE_HEADER,
        )

    raise GrantoraAPIError(
        status.HTTP_401_UNAUTHORIZED,
        "admin_auth_invalid",
        "Invalid admin token",
        AUTHENTICATE_HEADER,
    )


def _oidc_admin_principal(request: Request) -> AdminPrincipal | None:
    settings = request.app.state.settings
    if not settings.feature_oidc:
        return None

    subject = request.headers.get(settings.oidc_subject_header)
    if not subject:
        return None

    allowed_subjects = {
        item.strip() for item in settings.oidc_admin_subjects.split(",") if item.strip()
    }
    if subject not in allowed_subjects:
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            "admin_auth_invalid",
            "Invalid admin token",
            AUTHENTICATE_HEADER,
        )
    return AdminPrincipal(actor_type="admin_oidc", subject=subject)


def _store_admin_principal(request: Request, principal: AdminPrincipal) -> None:
    request.state.admin_actor_type = principal.actor_type
    request.state.admin_subject = principal.subject
    request.state.admin_workspace_id = (
        str(principal.workspace_id) if principal.workspace_id else None
    )


def extract_bearer_token(
    authorization: str | None,
    *,
    missing_code: str,
    invalid_code: str,
    invalid_message: str,
) -> str:
    if authorization is None:
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            missing_code,
            "Missing bearer token",
            AUTHENTICATE_HEADER,
        )

    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            invalid_code,
            invalid_message,
            AUTHENTICATE_HEADER,
        )

    return token.strip()


AuthenticatedAgent = Annotated[Agent, Depends(require_authenticated_agent)]
AdminBootstrap = Annotated[AdminPrincipal, Depends(require_admin_bootstrap)]
