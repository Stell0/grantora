from __future__ import annotations

import ipaddress
from typing import Annotated
from urllib.parse import urlparse

from pydantic import AfterValidator, Field

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
EXTERNAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._@:-]*$"
CAPABILITY_ID_PATTERN = r"^[a-z0-9][a-z0-9]*(?:[._-][a-z0-9]+)*$"
IDENTIFIER_PATTERN = r"^[a-z0-9][a-z0-9_]*(?:[._-][a-z0-9_]+)*$"
PERMISSION_CODE_PATTERN = r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
MCP_TOOL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_]*$"

Slug = Annotated[str, Field(min_length=1, max_length=64, pattern=SLUG_PATTERN)]
ExternalId = Annotated[str, Field(min_length=1, max_length=128, pattern=EXTERNAL_ID_PATTERN)]
CapabilityId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=CAPABILITY_ID_PATTERN),
]
ProviderType = Annotated[str, Field(min_length=1, max_length=64, pattern=IDENTIFIER_PATTERN)]
AdapterId = Annotated[str, Field(min_length=1, max_length=64, pattern=IDENTIFIER_PATTERN)]
OperationId = Annotated[str, Field(min_length=1, max_length=128, pattern=CAPABILITY_ID_PATTERN)]
PermissionCode = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=PERMISSION_CODE_PATTERN),
]
MCPToolName = Annotated[str, Field(min_length=1, max_length=128, pattern=MCP_TOOL_NAME_PATTERN)]
UpstreamBaseURL = Annotated[
    str,
    Field(min_length=1, max_length=2048),
    AfterValidator(lambda value: validate_upstream_base_url(value)),
]

_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}


def validate_upstream_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("base_url must use http or https")
    if not parsed.hostname:
        raise ValueError("base_url must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not include credentials")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("base_url must not include params, query or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("base_url must be an origin without a path")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in _LOCAL_HOSTNAMES or hostname.endswith(".localhost"):
        raise ValueError("base_url must not point to localhost")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if "." not in hostname:
            raise ValueError("base_url host must be a fully-qualified name") from None
    else:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError("base_url must not point to a local or private address")

    return value.rstrip("/")
