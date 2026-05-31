from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from grantora.config import Settings
from grantora.db.models import AuditEvent, UsageEvent, utc_now


@dataclass(frozen=True)
class RetentionResult:
    audit_deleted: int
    usage_deleted: int
    audit_cutoff: datetime
    usage_cutoff: datetime
    dry_run: bool = False


def purge_expired_events(
    session: Session,
    settings: Settings,
    *,
    reference_time: datetime | None = None,
    dry_run: bool = False,
) -> RetentionResult:
    now = reference_time or utc_now()
    audit_cutoff = now - timedelta(days=settings.audit_retention_days)
    usage_cutoff = now - timedelta(days=settings.usage_retention_days)
    audit_deleted = _prune_model(
        session,
        AuditEvent,
        AuditEvent.timestamp,
        cutoff=audit_cutoff,
        dry_run=dry_run,
    )
    usage_deleted = _prune_model(
        session,
        UsageEvent,
        UsageEvent.timestamp,
        cutoff=usage_cutoff,
        dry_run=dry_run,
    )
    return RetentionResult(
        audit_deleted=audit_deleted,
        usage_deleted=usage_deleted,
        audit_cutoff=audit_cutoff,
        usage_cutoff=usage_cutoff,
        dry_run=dry_run,
    )


def _prune_model(
    session: Session,
    model: type[AuditEvent] | type[UsageEvent],
    timestamp_column: object,
    *,
    cutoff: datetime,
    dry_run: bool,
) -> int:
    count_statement = select(func.count()).select_from(model).where(timestamp_column < cutoff)
    matches = int(session.execute(count_statement).scalar_one())
    if matches == 0 or dry_run:
        return matches

    session.execute(delete(model).where(timestamp_column < cutoff))
    return matches