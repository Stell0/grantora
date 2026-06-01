from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

from grantora.schemas.validation import CAPABILITY_ID_PATTERN, IDENTIFIER_PATTERN

FORBIDDEN_SCHEMA_REFERENCE_KEYS = {"$ref", "$dynamicRef"}
MAX_CAPABILITY_SCHEMA_DEPTH = 12
MAX_CAPABILITY_SCHEMA_NODES = 400
VALID_AUTH_MODES = {"system", "user", "user+scope", "admin"}
VALID_RISK_CLASSES = {"read_only", "draft", "side_effect", "destructive", "admin"}
VALID_SECRET_TYPES = {
    "api_key",
    "bearer_token",
    "basic_auth",
    "oauth_refresh_token",
    "session_cookie",
}
CAPABILITY_DEFINITION_ERROR_CODE = "capability_definition_invalid"
CAPABILITY_DEFINITION_ERROR_MESSAGE = "Capability definition is invalid"


class CapabilitySchemaValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def validate_capability_definition(
    *,
    capability_id: str,
    name: str,
    provider_type: str,
    adapter: str,
    operation: str,
    auth_mode: str,
    risk_class: str,
    input_schema: Mapping[str, Any],
    output_schema: Mapping[str, Any],
) -> None:
    _check_pattern_value(capability_id, CAPABILITY_ID_PATTERN, max_length=128)
    _check_text_value(name, max_length=255)
    _check_pattern_value(provider_type, IDENTIFIER_PATTERN, max_length=64)
    _check_pattern_value(adapter, IDENTIFIER_PATTERN, max_length=64)
    _check_pattern_value(operation, CAPABILITY_ID_PATTERN, max_length=128)
    if auth_mode not in VALID_AUTH_MODES or risk_class not in VALID_RISK_CLASSES:
        _raise_definition_error()
    check_json_schema(input_schema)
    check_json_schema(output_schema)


def validate_capability_template_definition(
    *,
    capability_id: str,
    name: str,
    provider_type: str,
    adapter: str,
    operation: str,
    auth_mode: str,
    risk_class: str,
    input_schema: Mapping[str, Any],
    output_schema: Mapping[str, Any],
    required_secret_types: tuple[str, ...],
    upstream_permissions: tuple[str, ...],
) -> None:
    validate_capability_definition(
        capability_id=capability_id,
        name=name,
        provider_type=provider_type,
        adapter=adapter,
        operation=operation,
        auth_mode=auth_mode,
        risk_class=risk_class,
        input_schema=input_schema,
        output_schema=output_schema,
    )
    if any(secret_type not in VALID_SECRET_TYPES for secret_type in required_secret_types):
        _raise_definition_error()
    for permission in upstream_permissions:
        _check_text_value(permission, max_length=128)


def check_json_schema(
    schema: Mapping[str, Any],
    *,
    schema_error_code: str = "capability_schema_invalid",
    schema_error_message: str = "Capability schema is invalid",
) -> None:
    _check_capability_schema_shape(
        schema,
        schema_error_code=schema_error_code,
        schema_error_message=schema_error_message,
    )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise CapabilitySchemaValidationError(schema_error_code, schema_error_message) from exc


def validate_json_schema(
    instance: Any,
    schema: Mapping[str, Any],
    *,
    validation_error_code: str,
    validation_message: str,
    schema_error_code: str = "capability_schema_invalid",
    schema_error_message: str = "Capability schema is invalid",
) -> None:
    check_json_schema(
        schema,
        schema_error_code=schema_error_code,
        schema_error_message=schema_error_message,
    )

    validator = Draft202012Validator(schema)
    if next(validator.iter_errors(instance), None) is not None:
        raise CapabilitySchemaValidationError(validation_error_code, validation_message)


def _check_capability_schema_shape(
    schema: Mapping[str, Any],
    *,
    schema_error_code: str,
    schema_error_message: str,
) -> None:
    if schema.get("type") != "object":
        raise CapabilitySchemaValidationError(schema_error_code, schema_error_message)
    if schema.get("additionalProperties") is not False:
        raise CapabilitySchemaValidationError(schema_error_code, schema_error_message)
    nodes = _walk_schema_nodes(schema, depth=0)
    if nodes > MAX_CAPABILITY_SCHEMA_NODES:
        raise CapabilitySchemaValidationError(schema_error_code, schema_error_message)


def _check_pattern_value(value: str, pattern: str, *, max_length: int) -> None:
    if not value or len(value) > max_length or re.fullmatch(pattern, value) is None:
        _raise_definition_error()


def _check_text_value(value: str, *, max_length: int) -> None:
    if not value or not value.strip() or len(value) > max_length:
        _raise_definition_error()


def _raise_definition_error() -> None:
    raise CapabilitySchemaValidationError(
        CAPABILITY_DEFINITION_ERROR_CODE,
        CAPABILITY_DEFINITION_ERROR_MESSAGE,
    )


def _walk_schema_nodes(value: Any, *, depth: int) -> int:
    if depth > MAX_CAPABILITY_SCHEMA_DEPTH:
        raise CapabilitySchemaValidationError(
            "capability_schema_invalid",
            "Capability schema is invalid",
        )
    if isinstance(value, Mapping):
        if any(key in FORBIDDEN_SCHEMA_REFERENCE_KEYS for key in value):
            raise CapabilitySchemaValidationError(
                "capability_schema_invalid",
                "Capability schema is invalid",
            )
        return 1 + sum(_walk_schema_nodes(item, depth=depth + 1) for item in value.values())
    if isinstance(value, list):
        return 1 + sum(_walk_schema_nodes(item, depth=depth + 1) for item in value)
    return 1
