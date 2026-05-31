from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from grantora.adapters.base import AdapterResult
from grantora.db.models import Capability

RETRYABLE_STATUS_CODES = {
    httpx.codes.TOO_MANY_REQUESTS,
}


@dataclass(frozen=True)
class RetryPolicy:
    read_only_attempts: int = 2


async def send_with_read_only_retries(
    capability: Capability,
    send: Callable[[], Awaitable[httpx.Response]],
    policy: RetryPolicy,
) -> tuple[httpx.Response | None, AdapterResult | None]:
    attempts = _attempts_for_capability(capability, policy)
    for attempt in range(attempts):
        try:
            response = await send()
        except httpx.TimeoutException:
            if attempt < attempts - 1:
                continue
            return None, AdapterResult.error(
                "upstream_timeout",
                "The upstream application timed out",
                retryable=True,
            )
        except httpx.RequestError:
            if attempt < attempts - 1:
                continue
            return None, AdapterResult.error(
                "upstream_error",
                "The upstream application could not be reached",
                retryable=True,
            )

        if attempt < attempts - 1 and _retryable_status(response.status_code):
            continue
        return response, None

    return None, AdapterResult.error(
        "upstream_error",
        "The upstream application could not be reached",
        retryable=True,
    )


def _attempts_for_capability(capability: Capability, policy: RetryPolicy) -> int:
    if getattr(capability, "risk_class", None) == "read_only":
        return max(policy.read_only_attempts, 1)
    return 1


def _retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES or status_code >= 500
