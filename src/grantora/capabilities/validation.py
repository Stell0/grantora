from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator, SchemaError


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
