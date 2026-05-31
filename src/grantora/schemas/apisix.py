from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApisixSyncErrorSummary(BaseModel):
    code: str
    message: str


class ApisixRouteDriftSummary(BaseModel):
    status: Literal["not_checked", "in_sync", "drifted", "error"] = "not_checked"
    checked_routes: int = 0
    drifted_routes: int = 0
    missing_routes: int = 0
    error: ApisixSyncErrorSummary | None = None


class AdminApisixStatusResponse(BaseModel):
    status: Literal["never_run", "ok", "error"]
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    checked_routes: int = 0
    changed_routes: int = 0
    error: ApisixSyncErrorSummary | None = None
    route_drift: ApisixRouteDriftSummary = Field(default_factory=ApisixRouteDriftSummary)


class AdminApisixSyncResponse(BaseModel):
    request_id: str
    status: Literal["never_run", "ok", "error"]
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    checked_routes: int = 0
    changed_routes: int = 0
    error: ApisixSyncErrorSummary | None = None
