from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityTemplate:
    id: str
    name: str
    version: int
    provider_type: str
    adapter: str
    operation: str
    auth_mode: str
    risk_class: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_secret_types: tuple[str, ...]
    upstream_permissions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "provider_type": self.provider_type,
            "adapter": self.adapter,
            "operation": self.operation,
            "auth_mode": self.auth_mode,
            "risk_class": self.risk_class,
            "input_schema": deepcopy(self.input_schema),
            "output_schema": deepcopy(self.output_schema),
            "required_secret_types": list(self.required_secret_types),
            "upstream_permissions": list(self.upstream_permissions),
        }


NETHVOICE_PHONEBOOK_SEARCH_TEMPLATE = CapabilityTemplate(
    id="nethvoice.phonebook.search",
    name="Search phonebook",
    version=1,
    provider_type="nethvoice",
    adapter="nethvoice",
    operation="phonebook.search",
    auth_mode="user",
    risk_class="read_only",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "contacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "display_name": {"type": "string"},
                        "phone": {"type": "string"},
                        "company": {"type": "string"},
                        "source": {"type": "string", "const": "nethvoice"},
                    },
                    "required": ["display_name", "phone", "company", "source"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["contacts"],
        "additionalProperties": False,
    },
    required_secret_types=("api_key", "bearer_token"),
    upstream_permissions=("phonebook:read",),
)


NEXTCLOUD_FILES_SEARCH_TEMPLATE = CapabilityTemplate(
    id="nextcloud.files.search",
    name="Search files",
    version=1,
    provider_type="nextcloud",
    adapter="nextcloud",
    operation="files.search",
    auth_mode="user",
    risk_class="read_only",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "display_name": {"type": "string"},
                        "mime_type": {"type": "string"},
                        "size": {"type": ["integer", "null"]},
                        "modified_at": {"type": ["string", "null"]},
                        "source": {"type": "string", "const": "nextcloud"},
                    },
                    "required": [
                        "path",
                        "display_name",
                        "mime_type",
                        "size",
                        "modified_at",
                        "source",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["files"],
        "additionalProperties": False,
    },
    required_secret_types=("basic_auth", "bearer_token"),
    upstream_permissions=("files:read", "search:read"),
)


CAPABILITY_TEMPLATES = {
    template.id: template
    for template in (NETHVOICE_PHONEBOOK_SEARCH_TEMPLATE, NEXTCLOUD_FILES_SEARCH_TEMPLATE)
}


def get_capability_template(template_id: str) -> CapabilityTemplate | None:
    return CAPABILITY_TEMPLATES.get(template_id)


def list_capability_templates(provider_type: str | None = None) -> list[CapabilityTemplate]:
    templates = sorted(CAPABILITY_TEMPLATES.values(), key=lambda template: template.id)
    if provider_type is None:
        return templates
    return [template for template in templates if template.provider_type == provider_type]
