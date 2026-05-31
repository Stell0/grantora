from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from grantora import __version__
from grantora.adapters import AdapterRegistry
from grantora.api.admin import router as admin_router
from grantora.api.errors import GrantoraAPIError, create_request_id, grantora_api_error_handler
from grantora.api.health import router as health_router
from grantora.api.runtime import router as runtime_router
from grantora.config import Settings, get_settings
from grantora.db import Database
from grantora.logging import configure_logging


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
    async def attach_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(resolved_settings.request_id_header) or create_request_id()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[resolved_settings.request_id_header] = request_id
        return response

    app.state.settings = resolved_settings
    app.state.database = resolved_database
    app.state.adapters = AdapterRegistry()
    app.add_exception_handler(GrantoraAPIError, grantora_api_error_handler)
    app.include_router(health_router)
    app.include_router(runtime_router)
    app.include_router(admin_router)
    return app
