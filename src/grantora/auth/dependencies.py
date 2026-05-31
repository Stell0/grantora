from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request, status
from sqlalchemy.orm import Session

from grantora.api.errors import GrantoraAPIError
from grantora.auth.tokens import hash_token, verify_token
from grantora.db.models import Agent
from grantora.db.queries import get_active_agent_by_token_hash

AUTHENTICATE_HEADER = {"WWW-Authenticate": "Bearer"}


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
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> None:
    token = extract_bearer_token(
        authorization,
        missing_code="admin_auth_missing",
        invalid_code="admin_auth_invalid",
        invalid_message="Invalid admin token",
    )
    settings = request.app.state.settings

    if not settings.admin_bootstrap_token_hash:
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            "admin_auth_unavailable",
            "Admin authentication is not configured",
            AUTHENTICATE_HEADER,
        )

    if not verify_token(token, settings.admin_bootstrap_token_hash, settings.agent_token_pepper):
        raise GrantoraAPIError(
            status.HTTP_401_UNAUTHORIZED,
            "admin_auth_invalid",
            "Invalid admin token",
            AUTHENTICATE_HEADER,
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
AdminBootstrap = Annotated[None, Depends(require_admin_bootstrap)]
