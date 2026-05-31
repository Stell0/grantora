from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CapabilitySummary(BaseModel):
    id: str
    name: str
    version: int
    provider_type: str
    operation: str
    auth_mode: str
    risk_class: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: str

    model_config = ConfigDict(from_attributes=True)


class CapabilityListResponse(BaseModel):
    capabilities: list[CapabilitySummary]
    limit: int
    offset: int


class CapabilityInvokeRequest(BaseModel):
    user: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)


class CapabilityInvokeResponse(BaseModel):
    request_id: str
    capability: str
    status: Literal["ok"]
    data: dict[str, Any]


class MCPToolDescriptor(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    meta: dict[str, Any] = Field(alias="_meta")

    model_config = ConfigDict(populate_by_name=True)


class MCPToolListResponse(BaseModel):
    tools: list[MCPToolDescriptor]


class MCPToolCallRequest(BaseModel):
    user: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPTextContent(BaseModel):
    type: Literal["text"]
    text: str


class MCPToolCallResponse(BaseModel):
    content: list[MCPTextContent]
    structured_content: dict[str, Any] = Field(alias="structuredContent")
    is_error: bool = Field(alias="isError")
    meta: dict[str, Any] = Field(alias="_meta")

    model_config = ConfigDict(populate_by_name=True)


class RuntimeUsageEventSummary(BaseModel):
    id: UUID
    timestamp: datetime
    workspace_id: UUID
    agent_id: UUID
    user_id: UUID | None
    capability_id: str
    application_instance_id: UUID | None
    units: int
    status: str
    latency_ms: int

    model_config = ConfigDict(from_attributes=True)


class RuntimeUsageAggregateSummary(BaseModel):
    workspace_id: UUID
    agent_id: UUID
    user_id: UUID | None
    capability_id: str
    status: str
    events: int
    total_units: int


class UsageMeResponse(BaseModel):
    usage: list[RuntimeUsageEventSummary]
    summaries: list[RuntimeUsageAggregateSummary]
    limit: int
    offset: int
