from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ApisixSyncErrorSummary(BaseModel):
    code: str
    message: str


class AdminApisixStatusResponse(BaseModel):
    status: Literal["never_run", "ok", "error"]
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    checked_routes: int = 0
    changed_routes: int = 0
    error: ApisixSyncErrorSummary | None = None


class AdminApisixSyncResponse(AdminApisixStatusResponse):
    request_id: str
