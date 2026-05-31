from __future__ import annotations

import secrets
from collections.abc import Mapping

from fastapi import Request
from fastapi.responses import JSONResponse


class GrantoraAPIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = dict(headers or {})


def create_request_id() -> str:
    return f"req_{secrets.token_urlsafe(16)}"


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id

    settings = request.app.state.settings
    header_request_id = request.headers.get(settings.request_id_header)
    if header_request_id:
        return header_request_id

    return create_request_id()


async def grantora_api_error_handler(request: Request, exc: GrantoraAPIError) -> JSONResponse:
    settings = request.app.state.settings
    request_id = get_request_id(request)
    headers = {settings.request_id_header: request_id, **exc.headers}
    return JSONResponse(
        status_code=exc.status_code,
        headers=headers,
        content={
            "request_id": request_id,
            "status": "error",
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        },
    )
