from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from grantora.db.models import UsageEvent


def record_usage_event(
    session: Session,
    *,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID | None,
    capability_id: str,
    application_instance_id: UUID | None,
    status: str,
    latency_ms: int,
    units: int = 1,
) -> None:
    session.add(
        UsageEvent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            capability_id=capability_id,
            application_instance_id=application_instance_id,
            units=units,
            status=status,
            latency_ms=latency_ms,
        )
    )