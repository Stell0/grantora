from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from grantora.db.models import AuditEvent


def record_audit_event(
    session: Session,
    *,
    request_id: str,
    actor_type: str = "agent",
    workspace_id: UUID,
    agent_id: UUID | None,
    user_id: UUID | None,
    capability_id: str | None,
    application_instance_id: UUID | None,
    decision: str,
    outcome: str,
    latency_ms: int,
    error_code: str | None = None,
    remote_addr: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            request_id=request_id,
            actor_type=actor_type,
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            capability_id=capability_id,
            application_instance_id=application_instance_id,
            decision=decision,
            outcome=outcome,
            error_code=error_code,
            latency_ms=latency_ms,
            remote_addr=remote_addr,
        )
    )
