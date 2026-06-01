from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from grantora.db.models import ApplicationInstance, Capability


@dataclass(frozen=True)
class WorkspaceContext:
    id: UUID
    slug: str


@dataclass(frozen=True)
class AgentContext:
    id: UUID
    slug: str


@dataclass(frozen=True)
class UserContext:
    id: UUID
    external_id: str


@dataclass(frozen=True)
class ApplicationContext:
    id: UUID
    provider_type: str
    base_url: str | None


@dataclass(frozen=True)
class CapabilityContext:
    id: str
    operation: str


@dataclass(frozen=True)
class InvocationContext:
    request_id: str
    workspace: WorkspaceContext
    agent: AgentContext
    user: UserContext
    application: ApplicationContext
    capability: CapabilityContext


@dataclass(frozen=True)
class SecretMaterial:
    secret_type: str
    value: str


@dataclass(frozen=True)
class AdapterResult:
    status: Literal["ok", "error"]
    data: dict[str, Any] = field(default_factory=dict)
    usage_units: int = 1
    upstream_status: int | None = None
    safe_metadata: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    safe_message: str | None = None
    retryable: bool = False

    @classmethod
    def ok(
        cls,
        data: dict[str, Any],
        *,
        usage_units: int = 1,
        upstream_status: int | None = None,
        safe_metadata: dict[str, Any] | None = None,
    ) -> AdapterResult:
        return cls(
            status="ok",
            data=data,
            usage_units=usage_units,
            upstream_status=upstream_status,
            safe_metadata=safe_metadata or {},
        )

    @classmethod
    def error(
        cls,
        error_code: str,
        safe_message: str,
        *,
        upstream_status: int | None = None,
        retryable: bool = False,
        safe_metadata: dict[str, Any] | None = None,
    ) -> AdapterResult:
        return cls(
            status="error",
            upstream_status=upstream_status,
            safe_metadata=safe_metadata or {},
            error_code=error_code,
            safe_message=safe_message,
            retryable=retryable,
        )


@dataclass(frozen=True)
class HealthResult:
    status: Literal["ok", "error"]
    safe_message: str | None = None


class Adapter(Protocol):
    id: str
    provider_type: str

    async def invoke(
        self,
        capability: Capability,
        input_data: dict[str, Any],
        context: InvocationContext,
        secret: SecretMaterial,
    ) -> AdapterResult: ...

    async def health(self, application: ApplicationInstance) -> HealthResult: ...
