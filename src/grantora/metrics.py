from __future__ import annotations

from time import perf_counter

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

REQUESTS_TOTAL = Counter(
    "grantora_requests_total",
    "Total Grantora HTTP requests.",
    ("workspace", "agent", "user", "capability", "status"),
    registry=REGISTRY,
)
REQUEST_DURATION_SECONDS = Histogram(
    "grantora_request_duration_seconds",
    "Grantora HTTP request latency in seconds.",
    ("workspace", "capability", "provider"),
    registry=REGISTRY,
)
AUTHORIZATION_DENIED_TOTAL = Counter(
    "grantora_authorization_denied_total",
    "Total denied Grantora authorization decisions.",
    ("workspace", "reason"),
    registry=REGISTRY,
)
UPSTREAM_REQUESTS_TOTAL = Counter(
    "grantora_upstream_requests_total",
    "Total upstream requests made by Grantora adapters.",
    ("workspace", "provider", "status"),
    registry=REGISTRY,
)
UPSTREAM_ERRORS_TOTAL = Counter(
    "grantora_upstream_errors_total",
    "Total upstream adapter errors returned to Grantora.",
    ("workspace", "provider", "error_code"),
    registry=REGISTRY,
)
SECRET_RESOLUTION_TOTAL = Counter(
    "grantora_secret_resolution_total",
    "Total secret resolution outcomes.",
    ("workspace", "provider", "result"),
    registry=REGISTRY,
)
APISIX_SYNC_TOTAL = Counter(
    "grantora_apisix_sync_total",
    "Total APISIX route reconciliation attempts.",
    ("status",),
    registry=REGISTRY,
)
APISIX_SYNC_DURATION_SECONDS = Histogram(
    "grantora_apisix_sync_duration_seconds",
    "APISIX route reconciliation latency in seconds.",
    registry=REGISTRY,
)

UNKNOWN = "unknown"


def now() -> float:
    return perf_counter()


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def record_http_request(
    *,
    started_at: float,
    status_code: int,
    workspace: str | None = None,
    agent: str | None = None,
    user: str | None = None,
    capability: str | None = None,
    provider: str | None = None,
) -> None:
    workspace_label = _label(workspace)
    capability_label = _label(capability)
    REQUESTS_TOTAL.labels(
        workspace=workspace_label,
        agent=_label(agent),
        user=_label(user),
        capability=capability_label,
        status=str(status_code),
    ).inc()
    REQUEST_DURATION_SECONDS.labels(
        workspace=workspace_label,
        capability=capability_label,
        provider=_label(provider),
    ).observe(max(perf_counter() - started_at, 0.0))


def record_authorization_denied(*, workspace: str | None, reason: str) -> None:
    AUTHORIZATION_DENIED_TOTAL.labels(workspace=_label(workspace), reason=reason).inc()


def record_upstream_result(
    *,
    workspace: str | None,
    provider: str | None,
    status_code: int | None,
    error_code: str | None,
) -> None:
    if status_code is not None:
        UPSTREAM_REQUESTS_TOTAL.labels(
            workspace=_label(workspace),
            provider=_label(provider),
            status=str(status_code),
        ).inc()
    if error_code is not None:
        UPSTREAM_ERRORS_TOTAL.labels(
            workspace=_label(workspace),
            provider=_label(provider),
            error_code=error_code,
        ).inc()


def record_secret_resolution(*, workspace: str | None, provider: str | None, result: str) -> None:
    SECRET_RESOLUTION_TOTAL.labels(
        workspace=_label(workspace),
        provider=_label(provider),
        result=result,
    ).inc()


def record_apisix_sync(*, status: str, duration_seconds: float) -> None:
    APISIX_SYNC_TOTAL.labels(status=status).inc()
    APISIX_SYNC_DURATION_SECONDS.observe(max(duration_seconds, 0.0))


def _label(value: object | None) -> str:
    if value is None:
        return UNKNOWN
    return str(value)
