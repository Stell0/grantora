from __future__ import annotations

from typing import Any

from grantora.adapters.base import AdapterResult, HealthResult, InvocationContext, SecretMaterial
from grantora.db.models import ApplicationInstance, Capability


class MockAdapter:
    id = "mock"
    provider_type = "mock"

    async def invoke(
        self,
        capability: Capability,
        input_data: dict[str, Any],
        context: InvocationContext,
        secret: SecretMaterial,
    ) -> AdapterResult:
        if capability.operation == "phonebook.search":
            return AdapterResult.ok(
                {"contacts": []},
                safe_metadata={"provider_type": self.provider_type},
            )
        return AdapterResult.ok(
            {
                "echo": input_data,
                "capability": context.capability.id,
            },
            safe_metadata={"provider_type": self.provider_type},
        )

    async def health(self, application: ApplicationInstance) -> HealthResult:
        return HealthResult(status="ok")
