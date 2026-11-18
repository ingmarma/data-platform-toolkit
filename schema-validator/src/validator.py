"""
Schema Validator — Core validation logic

Validates data against JSON Schema definitions stored in
AWS Glue Schema Registry.
"""

import json
import logging
from typing import Any, Optional

import boto3
import jsonschema
from jsonschema import ValidationError

logger = logging.getLogger(__name__)

glue = boto3.client("glue")


class SchemaValidator:
    """Validates data records against registered schemas."""

    def __init__(self, registry_name: str = "data-platform-schemas"):
        self.registry_name = registry_name
        self._schema_cache: dict[str, dict] = {}

    def validate(self, dataset: str, records: list[dict]) -> dict:
        """
        Validate records against the latest schema for the dataset.

        Returns:
            {
                "valid": bool,
                "errors": list[str],
                "records_checked": int,
                "schema_version": str,
                "schema_version_changed": bool,
                "previous_version": Optional[str],
                "current_version": str,
            }
        """
        schema_info = self._get_latest_schema(dataset)

        if not schema_info:
            logger.warning("No schema found for dataset '%s', skipping validation", dataset)
            return {
                "valid": True,
                "reason": "no_schema_registered",
                "records_checked": len(records),
            }

        schema = schema_info["schema"]
        version = schema_info["version"]
        previous_version = schema_info.get("previous_version")

        errors = []
        for i, record in enumerate(records):
            record_errors = self._validate_record(record, schema)
            for err in record_errors:
                errors.append(f"Record {i}: {err}")

        return {
            "valid": len(errors) == 0,
            "errors": errors[:50],  # Cap at 50 errors
            "records_checked": len(records),
            "schema_version": version,
            "schema_version_changed": previous_version is not None and previous_version != version,
            "previous_version": previous_version,
            "current_version": version,
        }

    def _validate_record(self, record: dict, schema: dict) -> list[str]:
        """Validate a single record against a JSON Schema."""
        errors = []
        try:
            jsonschema.validate(instance=record, schema=schema)
        except ValidationError as e:
            errors.append(f"{e.json_path}: {e.message}")
        except jsonschema.SchemaError as e:
            errors.append(f"Invalid schema: {e.message}")
        return errors

    def _get_latest_schema(self, dataset: str) -> Optional[dict]:
        """Fetch latest schema from Glue Schema Registry."""
        if dataset in self._schema_cache:
            return self._schema_cache[dataset]

        try:
            # Get schema versions
            response = glue.get_schema_version(
                SchemaId={
                    "RegistryName": self.registry_name,
                    "SchemaName": dataset,
                },
                SchemaVersionNumber={"LatestVersion": True},
            )

            schema_def = json.loads(response["SchemaDefinition"])
            version = str(response["SchemaVersionNumber"])

            # Try to get previous version
            previous_version = None
            version_num = response["SchemaVersionNumber"]
            if version_num > 1:
                try:
                    prev = glue.get_schema_version(
                        SchemaId={
                            "RegistryName": self.registry_name,
                            "SchemaName": dataset,
                        },
                        SchemaVersionNumber={"VersionNumber": version_num - 1},
                    )
                    previous_version = str(prev["SchemaVersionNumber"])
                except Exception:
                    pass

            result = {
                "schema": schema_def,
                "version": version,
                "previous_version": previous_version,
            }
            self._schema_cache[dataset] = result
            return result

        except glue.exceptions.EntityNotFoundException:
            logger.info("No schema registered for dataset '%s'", dataset)
            return None
        except Exception as e:
            logger.error("Failed to fetch schema for '%s': %s", dataset, e)
            return None


def validate_avro_schema(schema_str: str, record: dict) -> list[str]:
    """
    Validate a record against an Avro schema.

    Converts Avro schema to JSON Schema-compatible checks for
    field names and types.
    """
    import avro.schema

    errors = []
    try:
        schema = avro.schema.parse(schema_str)
        expected_fields = {f.name: f.type for f in schema.fields}

        for field_name, field_type in expected_fields.items():
            if field_name not in record:
                if not _is_nullable(field_type):
                    errors.append(f"Missing required field: {field_name}")
            else:
                type_error = _check_avro_type(record[field_name], field_type)
                if type_error:
                    errors.append(f"Field '{field_name}': {type_error}")

    except Exception as e:
        errors.append(f"Avro validation error: {e}")

    return errors


def _is_nullable(avro_type) -> bool:
    """Check if an Avro type is nullable (union with null)."""
    if isinstance(avro_type, list):
        return "null" in [str(t) for t in avro_type]
    return str(avro_type) == "null"


def _check_avro_type(value: Any, avro_type) -> Optional[str]:
    """Basic Avro type checking."""
    type_map = {
        "string": str,
        "int": int,
        "long": int,
        "float": (int, float),
        "double": (int, float),
        "boolean": bool,
    }

    type_str = str(avro_type)
    if type_str in type_map:
        expected = type_map[type_str]
        if not isinstance(value, expected):
            return f"expected {type_str}, got {type(value).__name__}"

    return None
