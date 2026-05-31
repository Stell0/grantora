from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from grantora.api.errors import GrantoraAPIError, get_request_id
from grantora.apisix import (
    ApisixAdminClient,
    ApisixSyncResult,
    get_apisix_sync_status,
    reconcile_apisix_routes,
)
from grantora.auth import TOKEN_HASH_ALGORITHM, create_agent_token, hash_token
from grantora.auth.dependencies import AdminBootstrap, DatabaseSession
from grantora.config import Settings
from grantora.db.models import Agent, ApisixSyncStatus
from grantora.db.queries import get_active_workspace_by_id
from grantora.schemas import (
    AdminAgentCreateRequest,
    AdminAgentCreateResponse,
    AdminAgentListResponse,
    AdminApisixStatusResponse,
    AdminApisixSyncResponse,
    AgentAdminSummary,
    ApisixSyncErrorSummary,
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


@router.post("/apisix/sync", response_model=AdminApisixSyncResponse)
async def sync_apisix_routes(
    request: Request,
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminApisixSyncResponse:
    settings = request.app.state.settings
    client_factory = _get_apisix_client_factory(request)
    async with client_factory(settings) as apisix_client:
        result = await reconcile_apisix_routes(session, settings, apisix_client)

    return _apisix_sync_response_from_result(get_request_id(request), result)


@router.get("/apisix/status", response_model=AdminApisixStatusResponse)
def get_apisix_status(
    _admin: AdminBootstrap,
    session: DatabaseSession,
) -> AdminApisixStatusResponse:
    sync_status = get_apisix_sync_status(session)
    if sync_status is None:
        return AdminApisixStatusResponse(status="never_run")
    return _apisix_status_response_from_model(sync_status)


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
) -> AdminApisixStatusResponse:
    return AdminApisixStatusResponse(
        status=sync_status.status,
        last_started_at=sync_status.last_started_at,
        last_finished_at=sync_status.last_finished_at,
        checked_routes=sync_status.checked_routes,
        changed_routes=sync_status.changed_routes,
        error=_apisix_error_summary(sync_status.error_code, sync_status.safe_message),
    )


def _apisix_error_summary(
    code: str | None,
    message: str | None,
) -> ApisixSyncErrorSummary | None:
    if code is None:
        return None
    return ApisixSyncErrorSummary(code=code, message=message or "APISIX sync failed")
