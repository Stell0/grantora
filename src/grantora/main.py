from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from grantora import __version__
from grantora.api.health import router as health_router
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
    app.state.settings = resolved_settings
    app.state.database = resolved_database
    app.include_router(health_router)
    return app
