from __future__ import annotations

from collections.abc import Iterable, Sequence
from copy import deepcopy
from typing import Any

from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from grantora import __version__
from grantora.db.models import Capability
from grantora.openapi.tools import capability_tool_name, capability_tool_name_map


def build_runtime_openapi(
    routes: Sequence[Any],
    *,
    public_base_url: str | None = None,
) -> dict[str, Any]:
    runtime_routes = [
        route
        for route in routes
        if isinstance(route, APIRoute) and "runtime" in route.tags and route.include_in_schema
    ]
    document = get_openapi(
        title="Grantora Runtime API",
        version=__version__,
        description="Authenticated runtime API for Grantora agents.",
        routes=runtime_routes,
    )
    _add_public_server(document, public_base_url)
    return document


def build_capability_openapi(
    capabilities: Iterable[Capability],
    *,
    user: str,
    public_base_url: str | None = None,
) -> dict[str, Any]:
    sorted_capabilities = sorted(capabilities, key=lambda capability: capability.id)
    tool_names = capability_tool_name_map(sorted_capabilities)
    document = {
        "openapi": "3.1.0",
        "info": {
            "title": "Grantora Allowed Capabilities",
            "version": __version__,
            "description": "Capability operations allowed for the authenticated agent and user.",
        },
        "paths": {
            f"/v1/invoke/{capability.id}": {
                "post": _capability_operation(
                    capability,
                    user=user,
                    tool_name=tool_names[capability.id],
                )
            }
            for capability in sorted_capabilities
        },
        "components": {
            "schemas": {
                "GrantoraError": {
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                            },
                            "required": ["code", "message"],
                            "additionalProperties": False,
                        }
                    },
                    "required": ["error"],
                    "additionalProperties": False,
                }
            }
        },
    }
    _add_public_server(document, public_base_url)
    return document


def _add_public_server(document: dict[str, Any], public_base_url: str | None) -> None:
    if public_base_url is None:
        return
    server_url = public_base_url.rstrip("/")
    if not server_url:
        return
    document["servers"] = [{"url": server_url}]


def capability_operation_id(capability_id: str) -> str:
    return f"invoke_{capability_tool_name(capability_id)}"


def _capability_operation(capability: Capability, *, user: str, tool_name: str) -> dict[str, Any]:
    return {
        "tags": ["capabilities"],
        "summary": capability.name,
        "operationId": f"invoke_{tool_name}",
        "x-grantora-capability-id": capability.id,
        "x-grantora-tool-name": tool_name,
        "x-grantora-risk-class": capability.risk_class,
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "user": {"type": "string", "const": user},
                            "input": deepcopy(capability.input_schema),
                        },
                        "required": ["user", "input"],
                        "additionalProperties": False,
                    }
                }
            },
        },
        "responses": {
            "200": {
                "description": "Capability invocation succeeded",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "request_id": {"type": "string"},
                                "capability": {"type": "string", "const": capability.id},
                                "status": {"type": "string", "enum": ["ok"]},
                                "data": deepcopy(capability.output_schema),
                            },
                            "required": ["request_id", "capability", "status", "data"],
                            "additionalProperties": False,
                        }
                    }
                },
            },
            "4XX": {
                "description": "Safe Grantora client error",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/GrantoraError"}}
                },
            },
            "5XX": {
                "description": "Safe Grantora server or upstream error",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/GrantoraError"}}
                },
            },
        },
    }
