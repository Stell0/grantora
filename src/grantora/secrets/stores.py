from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from grantora.config import Settings

EXTERNAL_SECRET_PREFIX = "external:"


@dataclass(frozen=True)
class SecretValue:
    value: str


class ExternalSecretStore(Protocol):
    def resolve(self, reference: str, settings: Settings) -> SecretValue:
        raise NotImplementedError


class DisabledExternalSecretStore:
    def resolve(self, reference: str, settings: Settings) -> SecretValue:
        raise ExternalSecretStoreError(
            "secret_unavailable",
            "Required upstream secret could not be used",
        )


class ExternalSecretStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def stored_external_secret_reference(reference: str) -> str:
    return f"{EXTERNAL_SECRET_PREFIX}{reference}"


def resolve_secret_value(
    stored_value: str,
    settings: Settings,
    *,
    external_store: ExternalSecretStore | None = None,
) -> SecretValue:
    if not stored_value.startswith(EXTERNAL_SECRET_PREFIX):
        return SecretValue(stored_value)

    if not settings.feature_external_secret_store:
        raise ExternalSecretStoreError(
            "secret_unavailable",
            "Required upstream secret could not be used",
        )

    reference = stored_value.removeprefix(EXTERNAL_SECRET_PREFIX)
    store = external_store or DisabledExternalSecretStore()
    return store.resolve(reference, settings)
