from __future__ import annotations

from typing import Any, Literal

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


class CapabilityInvokeRequest(BaseModel):
    user: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)


class CapabilityInvokeResponse(BaseModel):
    request_id: str
    capability: str
    status: Literal["ok"]
    data: dict[str, Any]