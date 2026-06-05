from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from grantora.apisix.client import ApisixAdminAPIError
from grantora.config import Settings
from grantora.db.models import ACTIVE_STATUS, ApisixRoute, ApisixSyncStatus, utc_now
from grantora.metrics import now, record_apisix_sync

APISIX_SYNC_STATUS_ID = "default"
DEFAULT_RUNTIME_ROUTE_ID = "gateway-runtime"
DEFAULT_RUNTIME_ROUTE_URI = "/v1/runtime/*"
MANAGED_ROUTE_LABEL_KEY = "grantora_managed"
MANAGED_ROUTE_LABEL_VALUE = "true"
ROUTE_ID_LABEL_KEY = "grantora_route_id"
DEFAULT_RUNTIME_ROUTE_URIS = (
    "/v1/me",
    "/v1/capabilities",
    "/v1/capabilities/openapi.json",
    "/v1/openapi.json",
    "/v1/invoke/*",
    "/v1/usage/me",
    "/v1/mcp/tools",
    "/v1/mcp/call",
)


class ApisixRouteClient(Protocol):
    async def get_route(self, route_id: str) -> dict[str, Any] | None: ...

    async def list_routes(self) -> dict[str, dict[str, Any]]: ...

    async def put_route(self, route_id: str, route: dict[str, Any]) -> dict[str, Any]: ...

    async def delete_route(self, route_id: str) -> bool: ...


@dataclass(frozen=True)
class ApisixSyncResult:
    status: Literal["ok", "error"]
    checked_routes: int
    changed_routes: int
    error_code: str | None = None
    safe_message: str | None = None


@dataclass(frozen=True)
class ApisixRouteDriftResult:
    status: Literal["in_sync", "drifted", "error"]
    checked_routes: int
    drifted_routes: int
    missing_routes: int
    error_code: str | None = None
    safe_message: str | None = None


async def reconcile_apisix_routes(
    session: Session,
    settings: Settings,
    client: ApisixRouteClient,
) -> ApisixSyncResult:
    started_at = utc_now()
    metrics_started_at = now()
    ensure_apisix_tables(session)
    ensure_default_runtime_route(session, settings)
    session.commit()

    routes = list(session.scalars(select(ApisixRoute).order_by(ApisixRoute.id)).all())
    changed_routes = 0
    try:
        if settings.apisix_fail_closed:
            current_routes = await _load_current_routes(routes, client)
            managed_routes = await client.list_routes()
        else:
            current_routes = {}
            managed_routes = {}

        for route in routes:
            desired_route = build_apisix_route_payload(route, settings)
            current_route = (
                current_routes[route.id]
                if settings.apisix_fail_closed
                else await client.get_route(route.id)
            )
            if current_route is None or not route_matches_desired(current_route, desired_route):
                await client.put_route(route.id, desired_route)
                changed_routes += 1

        if not settings.apisix_fail_closed:
            managed_routes = await client.list_routes()
        desired_route_ids = {route.id for route in routes}
        for route_id, current_route in managed_routes.items():
            if route_id not in desired_route_ids and route_is_grantora_managed(current_route):
                if await client.delete_route(route_id):
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


async def check_apisix_route_drift(
    session: Session,
    settings: Settings,
    client: ApisixRouteClient,
) -> ApisixRouteDriftResult:
    routes = desired_apisix_routes(session, settings)
    drifted_routes = 0
    missing_routes = 0
    try:
        for route in routes:
            desired_route = build_apisix_route_payload(route, settings)
            current_route = await client.get_route(route.id)
            if current_route is None:
                missing_routes += 1
                drifted_routes += 1
            elif not route_matches_desired(current_route, desired_route):
                drifted_routes += 1
    except ApisixAdminAPIError as exc:
        return ApisixRouteDriftResult(
            status="error",
            checked_routes=len(routes),
            drifted_routes=drifted_routes,
            missing_routes=missing_routes,
            error_code=exc.code,
            safe_message=exc.safe_message,
        )
    except Exception:
        return ApisixRouteDriftResult(
            status="error",
            checked_routes=len(routes),
            drifted_routes=drifted_routes,
            missing_routes=missing_routes,
            error_code="apisix_drift_check_failed",
            safe_message="APISIX route drift check failed",
        )

    return ApisixRouteDriftResult(
        status="drifted" if drifted_routes else "in_sync",
        checked_routes=len(routes),
        drifted_routes=drifted_routes,
        missing_routes=missing_routes,
    )


async def _load_current_routes(
    routes: list[ApisixRoute],
    client: ApisixRouteClient,
) -> dict[str, dict[str, Any] | None]:
    current_routes: dict[str, dict[str, Any] | None] = {}
    for route in routes:
        current_routes[route.id] = await client.get_route(route.id)
    return current_routes


def ensure_default_runtime_route(session: Session, settings: Settings) -> ApisixRoute:
    route = session.get(ApisixRoute, DEFAULT_RUNTIME_ROUTE_ID)
    if route is not None:
        return route

    route = default_runtime_route(settings)
    session.add(route)
    session.flush()
    return route


def ensure_apisix_tables(session: Session) -> None:
    bind = session.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    missing_tables = []
    if ApisixRoute.__tablename__ not in existing_tables:
        missing_tables.append(ApisixRoute.__table__)
    if ApisixSyncStatus.__tablename__ not in existing_tables:
        missing_tables.append(ApisixSyncStatus.__table__)
    if missing_tables:
        for table in missing_tables:
            table.create(bind=bind, checkfirst=True)


def desired_apisix_routes(session: Session, settings: Settings) -> list[ApisixRoute]:
    ensure_apisix_tables(session)
    routes = list(session.scalars(select(ApisixRoute).order_by(ApisixRoute.id)).all())
    if any(route.id == DEFAULT_RUNTIME_ROUTE_ID for route in routes):
        return routes
    return [default_runtime_route(settings), *routes]


def default_runtime_route(settings: Settings) -> ApisixRoute:
    return ApisixRoute(
        id=DEFAULT_RUNTIME_ROUTE_ID,
        name="Grantora runtime API",
        uri=DEFAULT_RUNTIME_ROUTE_URI,
        upstream=default_upstream(settings),
        plugins=baseline_plugins(settings),
    )


def build_apisix_route_payload(route: ApisixRoute, settings: Settings) -> dict[str, Any]:
    payload = {
        "name": route.name,
        "upstream": route.upstream,
        "plugins": {**baseline_plugins(settings), **route.plugins},
        "labels": managed_route_labels(route.id),
        "status": 1 if route.status == ACTIVE_STATUS else 0,
    }
    if route.id == DEFAULT_RUNTIME_ROUTE_ID:
        payload["uris"] = list(DEFAULT_RUNTIME_ROUTE_URIS)
    else:
        payload["uri"] = route.uri
    return payload


def route_matches_desired(current_route: dict[str, Any], desired_route: dict[str, Any]) -> bool:
    comparable_current = {key: current_route.get(key) for key in desired_route}
    return comparable_current == desired_route


def managed_route_labels(route_id: str) -> dict[str, str]:
    return {
        MANAGED_ROUTE_LABEL_KEY: MANAGED_ROUTE_LABEL_VALUE,
        ROUTE_ID_LABEL_KEY: route_id,
    }


def route_is_grantora_managed(route: dict[str, Any]) -> bool:
    labels = route.get("labels")
    return (
        isinstance(labels, dict)
        and labels.get(MANAGED_ROUTE_LABEL_KEY) == MANAGED_ROUTE_LABEL_VALUE
    )


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
    ensure_apisix_tables(session)
    return session.get(ApisixSyncStatus, APISIX_SYNC_STATUS_ID)
