from grantora.adapters.base import (
    Adapter,
    AdapterResult,
    AgentContext,
    ApplicationContext,
    CapabilityContext,
    HealthResult,
    InvocationContext,
    SecretMaterial,
    UserContext,
    WorkspaceContext,
)
from grantora.adapters.mock import MockAdapter
from grantora.adapters.nethvoice import NethVoicePhonebookAdapter
from grantora.adapters.nextcloud import NextcloudFilesAdapter
from grantora.adapters.registry import AdapterRegistry, create_default_adapter_registry
from grantora.adapters.templates import CapabilityTemplate

__all__ = [
    "Adapter",
    "AdapterRegistry",
    "AdapterResult",
    "AgentContext",
    "ApplicationContext",
    "CapabilityContext",
    "MockAdapter",
    "HealthResult",
    "InvocationContext",
    "SecretMaterial",
    "CapabilityTemplate",
    "NethVoicePhonebookAdapter",
    "NextcloudFilesAdapter",
    "UserContext",
    "WorkspaceContext",
    "create_default_adapter_registry",
]
