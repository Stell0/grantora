from __future__ import annotations

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from grantora.adapters import SecretMaterial
from grantora.config import Settings
from grantora.db.models import Capability, User
from grantora.db.queries import get_active_secret_for_owner
from grantora.metrics import record_secret_resolution
from grantora.secrets.encryption import SecretCipher
from grantora.secrets.stores import ExternalSecretStoreError, resolve_secret_value


class SecretResolutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def resolve_secret_material(
    session: Session,
    settings: Settings,
    capability: Capability,
    user: User,
) -> SecretMaterial:
    secret = None
    if capability.auth_mode in {"user", "user+scope"}:
        secret = get_active_secret_for_owner(
            session,
            capability.workspace_id,
            capability.application_instance_id,
            "user",
            user.id,
        )
    elif capability.auth_mode == "system":
        secret = get_active_secret_for_owner(
            session,
            capability.workspace_id,
            capability.application_instance_id,
            "workspace",
            capability.workspace_id,
        )
    else:
        record_secret_resolution(
            workspace=str(capability.workspace_id),
            provider=capability.provider_type,
            result="denied",
        )
        raise SecretResolutionError(
            "capability_denied",
            "Capability is not allowed for runtime invocation",
        )

    if secret is None:
        record_secret_resolution(
            workspace=str(capability.workspace_id),
            provider=capability.provider_type,
            result="not_found",
        )
        raise SecretResolutionError(
            "secret_not_found",
            "Required upstream secret was not found",
        )

    try:
        stored_value = SecretCipher(settings.secret_encryption_key).decrypt(secret.encrypted_value)
        value = resolve_secret_value(stored_value, settings).value
    except (InvalidToken, ValueError, ExternalSecretStoreError) as exc:
        record_secret_resolution(
            workspace=str(capability.workspace_id),
            provider=capability.provider_type,
            result="unavailable",
        )
        raise SecretResolutionError(
            "secret_unavailable",
            "Required upstream secret could not be used",
        ) from exc

    record_secret_resolution(
        workspace=str(capability.workspace_id),
        provider=capability.provider_type,
        result="success",
    )
    return SecretMaterial(secret_type=secret.secret_type, value=value)
