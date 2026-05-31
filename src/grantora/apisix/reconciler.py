from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from grantora.apisix.client import ApisixAdminAPIError
from grantora.config import Settings
from grantora.db.models import ACTIVE_STATUS, ApisixRoute, ApisixSyncStatus, utc_now
from grantora.metrics import now, record_apisix_sync

APISIX_SYNC_STATUS_ID = "default"
DEFAULT_RUNTIME_ROUTE_ID = "gateway-runtime"


class ApisixRouteClient(Protocol):
    async def get_route(self, route_id: str) -> dict[str, Any] | None: ...

    async def put_route(self, route_id: str, route: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ApisixSyncResult:
    status: Literal["ok", "error"]
    checked_routes: int
    changed_routes: int
    error_code: str | None = None
    safe_message: str | None = None


async def reconcile_apisix_routes(
    session: Session,
    settings: Settings,
    client: ApisixRouteClient,
) -> ApisixSyncResult:
    started_at = utc_now()
    metrics_started_at = now()
    ensure_default_runtime_route(session, settings)
    session.commit()

    routes = list(session.scalars(select(ApisixRoute).order_by(ApisixRoute.id)).all())
    changed_routes = 0
    try:
        for route in routes:
            desired_route = build_apisix_route_payload(route, settings)
            current_route = await client.get_route(route.id)
            if current_route is None or not route_matches_desired(current_route, desired_route):
                await client.put_route(route.id, desired_route)
                changed_routes += 1

        result = ApisixSyncResult(
            status="ok",
            checked_routes=len(routes),
            changed_routes=changed_routes,
        )
    except ApisixAdminAPIError as exc:
        session.rollback()
        result = ApisixSyncResult(
            status="error",
            checked_routes=len(routes),
            changed_routes=changed_routes,
            error_code=exc.code,
            safe_message=exc.safe_message,
        )
    except Exception:
        session.rollback()
        result = ApisixSyncResult(
            status="error",
            checked_routes=len(routes),
            changed_routes=changed_routes,
            error_code="apisix_sync_failed",
            safe_message="APISIX route reconciliation failed",
        )

    record_apisix_sync_status(session, result, started_at=started_at)
    session.commit()
    record_apisix_sync(status=result.status, duration_seconds=now() - metrics_started_at)
    return result


def ensure_default_runtime_route(session: Session, settings: Settings) -> ApisixRoute:
    route = session.get(ApisixRoute, DEFAULT_RUNTIME_ROUTE_ID)
    if route is not None:
        return route

    route = ApisixRoute(
        id=DEFAULT_RUNTIME_ROUTE_ID,
        name="Grantora runtime API",
        uri="/v1/*",
        upstream=default_upstream(settings),
        plugins=baseline_plugins(settings),
    )
    session.add(route)
    session.flush()
    return route


def build_apisix_route_payload(route: ApisixRoute, settings: Settings) -> dict[str, Any]:
    return {
        "name": route.name,
        "uri": route.uri,
        "upstream": route.upstream,
        "plugins": {**baseline_plugins(settings), **route.plugins},
        "status": 1 if route.status == ACTIVE_STATUS else 0,
    }


def route_matches_desired(current_route: dict[str, Any], desired_route: dict[str, Any]) -> bool:
    comparable_current = {key: current_route.get(key) for key in desired_route}
    return comparable_current == desired_route


def baseline_plugins(settings: Settings) -> dict[str, Any]:
    return {
        "prometheus": {},
        "request-id": {},
        "limit-count": {
            "count": settings.apisix_rate_limit_count,
            "time_window": settings.apisix_rate_limit_time_window,
            "rejected_code": 429,
        },
    }


def default_upstream(settings: Settings) -> dict[str, Any]:
    return {
        "type": "roundrobin",
        "nodes": {settings.apisix_runtime_upstream_node: 1},
    }


def record_apisix_sync_status(
    session: Session,
    result: ApisixSyncResult,
    *,
    started_at: datetime,
) -> ApisixSyncStatus:
    sync_status = session.get(ApisixSyncStatus, APISIX_SYNC_STATUS_ID)
    if sync_status is None:
        sync_status = ApisixSyncStatus(id=APISIX_SYNC_STATUS_ID, status=result.status)
        session.add(sync_status)

    sync_status.status = result.status
    sync_status.last_started_at = started_at
    sync_status.last_finished_at = utc_now()
    sync_status.checked_routes = result.checked_routes
    sync_status.changed_routes = result.changed_routes
    sync_status.error_code = result.error_code
    sync_status.safe_message = result.safe_message
    return sync_status


def get_apisix_sync_status(session: Session) -> ApisixSyncStatus | None:
    return session.get(ApisixSyncStatus, APISIX_SYNC_STATUS_ID)
