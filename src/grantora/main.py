import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry.trace import SpanKind

from grantora import __version__
from grantora.adapters import create_default_adapter_registry
from grantora.api.admin import router as admin_router
from grantora.api.errors import GrantoraAPIError, create_request_id, grantora_api_error_handler
from grantora.api.health import router as health_router
from grantora.api.runtime import router as runtime_router
from grantora.apisix import ApisixAdminClient
from grantora.apisix.reconciler import reconcile_apisix_routes
from grantora.config import Settings, get_settings
from grantora.db import Database
from grantora.logging import configure_logging
from grantora.metrics import now, record_http_request, render_metrics
from grantora.tracing import TraceManager, create_trace_manager, span_ids

LOGGER = logging.getLogger("grantora.http")
APISIX_SYNC_LOGGER = logging.getLogger("grantora.apisix.sync")


def create_apisix_admin_client(settings: Settings) -> ApisixAdminClient:
    return ApisixAdminClient(
        settings.apisix_admin_url,
        settings.apisix_admin_key,
        timeout_seconds=settings.apisix_admin_timeout_seconds,
    )


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    trace_manager: TraceManager | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    resolved_database = database or Database(resolved_settings)
    resolved_trace_manager = trace_manager or create_trace_manager(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        apisix_sync_task: asyncio.Task[None] | None = None
        if hasattr(app.state.database, "create_schema"):
            app.state.database.create_schema()
        if resolved_settings.apisix_sync_enabled:
            await _run_apisix_sync_once(app)
            apisix_sync_task = asyncio.create_task(
                _run_apisix_sync_loop(app),
                name="grantora-apisix-sync",
            )

        try:
            yield
        finally:
            if apisix_sync_task is not None:
                apisix_sync_task.cancel()
                with suppress(asyncio.CancelledError):
                    await apisix_sync_task
            app.state.database.dispose()
            app.state.trace_manager.shutdown()

    app = FastAPI(
        title="Grantora Gateway API",
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def observe_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started_at = now()
        request_id = request.headers.get(resolved_settings.request_id_header) or create_request_id()
        request.state.request_id = request_id
        with resolved_trace_manager.start_as_current_span(
            "http.request",
            carrier=_trace_carrier(request),
            kind=SpanKind.SERVER,
            attributes={
                "http.request.method": request.method,
                "url.path": request.url.path,
                "grantora.request_id": request_id,
            },
        ) as span:
            trace_id, request_span_id = span_ids(span)
            request.state.trace_id = trace_id
            request.state.span_id = request_span_id
            if _request_body_exceeds_limit(request, resolved_settings.max_request_body_bytes):
                response = _safe_error_response(
                    request,
                    request_id=request_id,
                    status_code=413,
                    error_code="request_body_too_large",
                    message="Request body is too large",
                )
                resolved_trace_manager.inject_current_context(response.headers)
                _set_span_request_attributes(
                    span,
                    request,
                    request_id,
                    status_code=response.status_code,
                )
                record_http_request(
                    started_at=started_at,
                    status_code=response.status_code,
                    workspace=getattr(request.state, "workspace_id", None),
                    agent=getattr(request.state, "agent_id", None),
                    user=getattr(request.state, "user_id", None),
                    capability=getattr(request.state, "capability_id", None),
                    provider=getattr(request.state, "provider_type", None),
                )
                LOGGER.warning(
                    "request rejected",
                    extra=_request_log_context(
                        request,
                        request_id,
                        response.status_code,
                        started_at,
                    )
                    | {"error_code": "request_body_too_large"},
                )
                return response
            try:
                response = await call_next(request)
            except Exception:
                _set_span_request_attributes(span, request, request_id, status_code=500)
                record_http_request(
                    started_at=started_at,
                    status_code=500,
                    workspace=getattr(request.state, "workspace_id", None),
                    agent=getattr(request.state, "agent_id", None),
                    user=getattr(request.state, "user_id", None),
                    capability=getattr(request.state, "capability_id", None),
                    provider=getattr(request.state, "provider_type", None),
                )
                LOGGER.exception(
                    "request failed",
                    extra=_request_log_context(request, request_id, 500, started_at),
                )
                raise

            response.headers[resolved_settings.request_id_header] = request_id
            resolved_trace_manager.inject_current_context(response.headers)
            _set_span_request_attributes(
                span,
                request,
                request_id,
                status_code=response.status_code,
            )
            record_http_request(
                started_at=started_at,
                status_code=response.status_code,
                workspace=getattr(request.state, "workspace_id", None),
                agent=getattr(request.state, "agent_id", None),
                user=getattr(request.state, "user_id", None),
                capability=getattr(request.state, "capability_id", None),
                provider=getattr(request.state, "provider_type", None),
            )
            LOGGER.info(
                "request completed",
                extra=_request_log_context(request, request_id, response.status_code, started_at),
            )
            return response

    if resolved_settings.metrics_enabled:

        @app.get("/metrics", include_in_schema=False)
        def get_metrics() -> Response:
            content, media_type = render_metrics()
            return Response(content=content, media_type=media_type)

    app.state.settings = resolved_settings
    app.state.database = resolved_database
    app.state.adapters = create_default_adapter_registry(resolved_settings)
    app.state.apisix_client_factory = create_apisix_admin_client
    app.state.trace_manager = resolved_trace_manager
    app.add_exception_handler(GrantoraAPIError, grantora_api_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.include_router(health_router)
    app.include_router(runtime_router)
    app.include_router(admin_router)
    return app


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or create_request_id()
    return _safe_error_response(
        request,
        request_id=request_id,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        error_code="request_validation_failed",
        message="Request validation failed",
    )


async def _run_apisix_sync_loop(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    while True:
        await asyncio.sleep(settings.apisix_sync_interval_seconds)
        await _run_apisix_sync_once(app)


async def _run_apisix_sync_once(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    database: Database = app.state.database
    client_factory = app.state.apisix_client_factory
    trace_manager: TraceManager = app.state.trace_manager
    with trace_manager.start_as_current_span(
        "apisix.sync",
        kind=SpanKind.INTERNAL,
        attributes={"grantora.component": "apisix"},
    ) as span:
        try:
            with database.session_factory() as session:
                async with client_factory(settings) as apisix_client:
                    result = await reconcile_apisix_routes(session, settings, apisix_client)
        except Exception:
            if span.is_recording():
                span.set_attribute("grantora.apisix.status", "error")
                span.set_attribute("grantora.apisix.error_code", "apisix_sync_failed")
            APISIX_SYNC_LOGGER.error(
                "automatic APISIX sync failed",
                extra={"error_code": "apisix_sync_failed"},
            )
            return

        if span.is_recording():
            span.set_attribute("grantora.apisix.status", result.status)
            span.set_attribute("grantora.apisix.checked_routes", result.checked_routes)
            span.set_attribute("grantora.apisix.changed_routes", result.changed_routes)
            if result.error_code is not None:
                span.set_attribute("grantora.apisix.error_code", result.error_code)

        if result.status == "error":
            APISIX_SYNC_LOGGER.warning(
                "automatic APISIX sync completed with error",
                extra={"error_code": result.error_code, "checked_routes": result.checked_routes},
            )
            return

        APISIX_SYNC_LOGGER.info(
            "automatic APISIX sync completed",
            extra={
                "checked_routes": result.checked_routes,
                "changed_routes": result.changed_routes,
            },
        )


def _request_log_context(
    request: Request,
    request_id: str,
    status_code: int,
    started_at: float,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "trace_id": getattr(request.state, "trace_id", None),
        "span_id": getattr(request.state, "span_id", None),
        "workspace_id": getattr(request.state, "workspace_id", None),
        "agent_id": getattr(request.state, "agent_id", None),
        "user_id": getattr(request.state, "user_id", None),
        "capability_id": getattr(request.state, "capability_id", None),
        "provider_type": getattr(request.state, "provider_type", None),
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": max(int((now() - started_at) * 1000), 0),
    }


def _request_body_exceeds_limit(request: Request, max_bytes: int) -> bool:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return False
    try:
        return int(content_length) > max_bytes
    except ValueError:
        return True


def _safe_error_response(
    request: Request,
    *,
    request_id: str,
    status_code: int,
    error_code: str,
    message: str,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    return JSONResponse(
        status_code=status_code,
        headers={settings.request_id_header: request_id},
        content={
            "request_id": request_id,
            "status": "error",
            "error": {"code": error_code, "message": message},
        },
    )


def _set_span_request_attributes(
    span: object,
    request: Request,
    request_id: str,
    *,
    status_code: int,
) -> None:
    if not hasattr(span, "is_recording") or not span.is_recording():
        return

    span.set_attribute("http.response.status_code", status_code)
    span.set_attribute("grantora.request_id", request_id)
    for attribute, value in (
        ("grantora.workspace_id", getattr(request.state, "workspace_id", None)),
        ("grantora.agent_id", getattr(request.state, "agent_id", None)),
        ("grantora.user_id", getattr(request.state, "user_id", None)),
        ("grantora.capability_id", getattr(request.state, "capability_id", None)),
        ("grantora.provider_type", getattr(request.state, "provider_type", None)),
    ):
        if value is not None:
            span.set_attribute(attribute, value)


def _trace_carrier(request: Request) -> dict[str, str]:
    carrier: dict[str, str] = {}
    for header in ("traceparent", "tracestate"):
        value = request.headers.get(header)
        if value:
            carrier[header] = value
    return carrier
