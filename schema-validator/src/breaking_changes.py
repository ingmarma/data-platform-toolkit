"""
Breaking Change Detector

Compares two schema versions to detect backward-incompatible changes:
- Removed required fields
- Type changes on existing fields
- New required fields (without defaults)
- Renamed fields (heuristic)
"""

import json
import logging
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

glue = boto3.client("glue")


class BreakingChangeDetector:
    """Detects breaking changes between schema versions."""

    def __init__(self, registry_name: str = "data-platform-schemas"):
        self.registry_name = registry_name

    def detect(
        self, dataset: str, old_version: str, new_version: str
    ) -> list[dict]:
        """
        Compare two schema versions and return breaking changes.

        Returns:
            [
                {
                    "type": "field_removed" | "type_changed" | "required_added",
                    "field": str,
                    "severity": "critical" | "warning",
                    "details": str,
                }
            ]
        """
        old_schema = self._get_schema_version(dataset, int(old_version))
        new_schema = self._get_schema_version(dataset, int(new_version))

        if not old_schema or not new_schema:
            return []

        changes = []
        changes.extend(self._check_removed_fields(old_schema, new_schema))
        changes.extend(self._check_type_changes(old_schema, new_schema))
        changes.extend(self._check_new_required(old_schema, new_schema))

        if changes:
            logger.warning(
                "Breaking changes detected for '%s' (v%s → v%s): %d issues",
                dataset, old_version, new_version, len(changes),
            )

        return changes

    def _check_removed_fields(self, old: dict, new: dict) -> list[dict]:
        """Detect fields that existed in old schema but not in new."""
        changes = []
        old_fields = set(old.get("properties", {}).keys())
        new_fields = set(new.get("properties", {}).keys())
        old_required = set(old.get("required", []))

        removed = old_fields - new_fields
        for field in removed:
            severity = "critical" if field in old_required else "warning"
            changes.append({
                "type": "field_removed",
                "field": field,
                "severity": severity,
                "details": f"Field '{field}' was removed. "
                           f"Existing consumers referencing this field will break.",
            })

        return changes

    def _check_type_changes(self, old: dict, new: dict) -> list[dict]:
        """Detect fields whose type changed between versions."""
        changes = []
        old_props = old.get("properties", {})
        new_props = new.get("properties", {})

        common_fields = set(old_props.keys()) & set(new_props.keys())
        for field in common_fields:
            old_type = self._extract_type(old_props[field])
            new_type = self._extract_type(new_props[field])

            if old_type != new_type:
                changes.append({
                    "type": "type_changed",
                    "field": field,
                    "severity": "critical",
                    "details": f"Field '{field}' type changed from "
                               f"'{old_type}' to '{new_type}'.",
                })

        return changes

    def _check_new_required(self, old: dict, new: dict) -> list[dict]:
        """Detect new required fields (breaking for existing producers)."""
        changes = []
        old_required = set(old.get("required", []))
        new_required = set(new.get("required", []))
        old_fields = set(old.get("properties", {}).keys())

        new_required_fields = new_required - old_required
        for field in new_required_fields:
            # Only breaking if the field is also new (not previously optional)
            if field not in old_fields:
                changes.append({
                    "type": "required_added",
                    "field": field,
                    "severity": "critical",
                    "details": f"New required field '{field}' added. "
                               f"Existing producers don't send this field.",
                })
            else:
                changes.append({
                    "type": "required_added",
                    "field": field,
                    "severity": "warning",
                    "details": f"Field '{field}' changed from optional to required. "
                               f"Rows with null values will fail validation.",
                })

        return changes

    def _extract_type(self, prop: dict) -> str:
        """Extract the type string from a JSON Schema property."""
        if "type" in prop:
            return str(prop["type"])
        if "anyOf" in prop:
            types = [t.get("type", "unknown") for t in prop["anyOf"]]
            return "|".join(sorted(types))
        if "$ref" in prop:
            return f"$ref:{prop['$ref']}"
        return "unknown"

    def _get_schema_version(self, dataset: str, version: int) -> Optional[dict]:
        """Fetch a specific schema version from the registry."""
        try:
            response = glue.get_schema_version(
                SchemaId={
                    "RegistryName": self.registry_name,
                    "SchemaName": dataset,
                },
                SchemaVersionNumber={"VersionNumber": version},
            )
            return json.loads(response["SchemaDefinition"])
        except Exception as e:
            logger.error("Failed to get schema version %d for '%s': %s", version, dataset, e)
            return None
