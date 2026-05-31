from fastapi import APIRouter, Request, Response, status

from grantora import __version__

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": "grantora-api",
        "environment": settings.environment,
        "version": __version__,
    }


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict[str, object]:
    try:
        request.app.state.database.ping()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "error",
            "service": "grantora-api",
            "checks": {"database": "unavailable"},
        }

    return {
        "status": "ok",
        "service": "grantora-api",
        "checks": {"database": "ok"},
    }
