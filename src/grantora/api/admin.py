from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from grantora.api.errors import GrantoraAPIError
from grantora.auth import TOKEN_HASH_ALGORITHM, create_agent_token, hash_token
from grantora.auth.dependencies import AdminBootstrap, DatabaseSession
from grantora.db.models import Agent
from grantora.db.queries import get_active_workspace_by_id
from grantora.schemas import (
    AdminAgentCreateRequest,
    AdminAgentCreateResponse,
    AdminAgentListResponse,
    AgentAdminSummary,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


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

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise GrantoraAPIError(
            status.HTTP_409_CONFLICT,
            "agent_conflict",
            "Agent could not be created",
        ) from exc

    return AdminAgentCreateResponse(
        agent=AgentAdminSummary.model_validate(agent),
        token=plaintext_token,
    )


@router.get("/agents", response_model=AdminAgentListResponse)
def list_agents(
    _admin: AdminBootstrap,
    session: DatabaseSession,
    workspace_id: UUID | None = None,
) -> AdminAgentListResponse:
    statement = select(Agent).order_by(Agent.slug)
    if workspace_id is not None:
        statement = statement.where(Agent.workspace_id == workspace_id)

    agents = session.scalars(statement).all()
    return AdminAgentListResponse(
        agents=[AgentAdminSummary.model_validate(agent) for agent in agents]
    )
