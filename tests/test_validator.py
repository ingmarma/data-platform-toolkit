"""Tests for Schema Validator module."""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestSchemaValidator:
    """Test schema validation logic."""

    def test_valid_record_passes(self):
        """A record matching the schema should pass."""
        from schema_validator.src.validator import SchemaValidator

        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "amount": {"type": "number"},
            },
            "required": ["id", "name"],
        }

        validator = SchemaValidator.__new__(SchemaValidator)
        validator.schema_cache = {}

        result = validator._validate_json(
            {"id": "123", "name": "Test", "amount": 42.0},
            schema,
        )
        assert result["valid"] is True

    def test_missing_required_field_fails(self):
        """Missing a required field should fail validation."""
        from schema_validator.src.validator import SchemaValidator

        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["id", "name"],
        }

        validator = SchemaValidator.__new__(SchemaValidator)
        validator.schema_cache = {}

        result = validator._validate_json(
            {"id": "123"},  # missing 'name'
            schema,
        )
        assert result["valid"] is False
        assert "name" in str(result.get("errors", []))

    def test_wrong_type_fails(self):
        """A field with the wrong type should fail."""
        from schema_validator.src.validator import SchemaValidator

        schema = {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
            },
        }

        validator = SchemaValidator.__new__(SchemaValidator)
        validator.schema_cache = {}

        result = validator._validate_json(
            {"amount": "not_a_number"},
            schema,
        )
        assert result["valid"] is False


class TestBreakingChanges:
    """Test breaking change detection."""

    def test_removed_field_is_critical(self):
        """Removing a field should be detected as critical."""
        from schema_validator.src.breaking_changes import BreakingChangeDetector

        old_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }

        new_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                # email removed
            },
        }

        detector = BreakingChangeDetector()
        changes = detector.detect(old_schema, new_schema)

        assert len(changes) > 0
        assert any(c["field"] == "email" for c in changes)
        assert any(c["severity"] == "critical" for c in changes)

    def test_type_change_is_critical(self):
        """Changing a field's type should be critical."""
        from schema_validator.src.breaking_changes import BreakingChangeDetector

        old = {"type": "object", "properties": {"age": {"type": "integer"}}}
        new = {"type": "object", "properties": {"age": {"type": "string"}}}

        detector = BreakingChangeDetector()
        changes = detector.detect(old, new)

        assert len(changes) > 0
        assert changes[0]["severity"] == "critical"

    def test_new_required_field_is_warning(self):
        """Adding a new required field is a warning."""
        from schema_validator.src.breaking_changes import BreakingChangeDetector

        old = {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        }
        new = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "created_at": {"type": "string"},
            },
            "required": ["id", "created_at"],
        }

        detector = BreakingChangeDetector()
        changes = detector.detect(old, new)

        assert len(changes) > 0
        assert any(c["severity"] == "warning" for c in changes)

    def test_no_breaking_changes(self):
        """Adding an optional field should produce no changes."""
        from schema_validator.src.breaking_changes import BreakingChangeDetector

        old = {"type": "object", "properties": {"id": {"type": "string"}}}
        new = {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "description": {"type": "string"},
            },
        }

        detector = BreakingChangeDetector()
        changes = detector.detect(old, new)

        assert len(changes) == 0
