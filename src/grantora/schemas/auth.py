from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSummary(BaseModel):
    id: UUID
    slug: str
    display_name: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class AgentSummary(BaseModel):
    id: UUID
    slug: str
    display_name: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class AgentAdminSummary(AgentSummary):
    workspace_id: UUID


class MeResponse(BaseModel):
    agent: AgentSummary
    workspace: WorkspaceSummary


class AdminAgentCreateRequest(BaseModel):
    workspace_id: UUID
    slug: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)


class AdminAgentCreateResponse(BaseModel):
    agent: AgentAdminSummary
    token: str


class AdminAgentListResponse(BaseModel):
    agents: list[AgentAdminSummary]
