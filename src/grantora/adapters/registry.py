from __future__ import annotations

from collections.abc import Iterable

from grantora.adapters.base import Adapter


class AdapterRegistry:
    def __init__(self, adapters: Iterable[Adapter] = ()) -> None:
        self._adapters: dict[str, Adapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: Adapter) -> None:
        self._adapters[adapter.id] = adapter

    def get(self, adapter_id: str) -> Adapter | None:
        return self._adapters.get(adapter_id)