from fastapi import APIRouter

from grantora.auth.dependencies import AuthenticatedAgent
from grantora.schemas import AgentSummary, MeResponse, WorkspaceSummary

router = APIRouter(prefix="/v1", tags=["runtime"])


@router.get("/me", response_model=MeResponse)
def get_me(agent: AuthenticatedAgent) -> MeResponse:
    return MeResponse(
        agent=AgentSummary.model_validate(agent),
        workspace=WorkspaceSummary.model_validate(agent.workspace),
    )
