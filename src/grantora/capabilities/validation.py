from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator, SchemaError

FORBIDDEN_SCHEMA_REFERENCE_KEYS = {"$ref", "$dynamicRef"}
MAX_CAPABILITY_SCHEMA_DEPTH = 12
MAX_CAPABILITY_SCHEMA_NODES = 400


class CapabilitySchemaValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


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
