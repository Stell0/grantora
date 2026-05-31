import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from grantora import __version__
from grantora.adapters import create_default_adapter_registry
from grantora.api.admin import router as admin_router
from grantora.api.errors import GrantoraAPIError, create_request_id, grantora_api_error_handler
from grantora.api.health import router as health_router
from grantora.api.runtime import router as runtime_router
from grantora.apisix import ApisixAdminClient
from grantora.config import Settings, get_settings
from grantora.db import Database
from grantora.logging import configure_logging
from grantora.metrics import now, record_http_request, render_metrics

LOGGER = logging.getLogger("grantora.http")


def create_apisix_admin_client(settings: Settings) -> ApisixAdminClient:
    return ApisixAdminClient(
        settings.apisix_admin_url,
        settings.apisix_admin_key,
        timeout_seconds=settings.apisix_admin_timeout_seconds,
    )


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    resolved_database = database or Database(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        app.state.database.dispose()

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
        try:
            response = await call_next(request)
        except Exception:
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
    app.add_exception_handler(GrantoraAPIError, grantora_api_error_handler)
    app.include_router(health_router)
    app.include_router(runtime_router)
    app.include_router(admin_router)
    return app


def _request_log_context(
    request: Request,
    request_id: str,
    status_code: int,
    started_at: float,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "workspace_id": getattr(request.state, "workspace_id", None),
        "agent_id": getattr(request.state, "agent_id", None),
        "user_id": getattr(request.state, "user_id", None),
        "capability_id": getattr(request.state, "capability_id", None),
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": max(int((now() - started_at) * 1000), 0),
    }
