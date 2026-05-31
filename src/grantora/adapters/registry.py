from __future__ import annotations

from collections.abc import Iterable

from grantora.adapters.base import Adapter
from grantora.config import Settings


class AdapterRegistry:
    def __init__(self, adapters: Iterable[Adapter] = ()) -> None:
        self._adapters: dict[str, Adapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: Adapter) -> None:
        self._adapters[adapter.id] = adapter

    def get(self, adapter_id: str) -> Adapter | None:
        return self._adapters.get(adapter_id)


def create_default_adapter_registry(settings: Settings | None = None) -> AdapterRegistry:
    from grantora.adapters.mock import MockAdapter
    from grantora.adapters.nethvoice import NethVoicePhonebookAdapter
    from grantora.adapters.nextcloud import NextcloudFilesAdapter

    if settings is None:
        return AdapterRegistry(
            [MockAdapter(), NethVoicePhonebookAdapter(), NextcloudFilesAdapter()]
        )
    return AdapterRegistry(
        [
            MockAdapter(),
            NethVoicePhonebookAdapter(
                timeout_seconds=settings.upstream_timeout_seconds,
                connect_timeout_seconds=settings.upstream_connect_timeout_seconds,
                max_response_bytes=settings.upstream_max_response_bytes,
                verify=settings.upstream_tls_verify,
                read_retry_attempts=settings.upstream_read_retry_attempts,
            ),
            NextcloudFilesAdapter(
                timeout_seconds=settings.upstream_timeout_seconds,
                connect_timeout_seconds=settings.upstream_connect_timeout_seconds,
                max_response_bytes=settings.upstream_max_response_bytes,
                verify=settings.upstream_tls_verify,
                read_retry_attempts=settings.upstream_read_retry_attempts,
            ),
        ]
    )
