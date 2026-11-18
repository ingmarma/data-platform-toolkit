"""Tests for Self-Service Queries module."""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestAthenaExecutor:
    """Test query execution and parameter handling."""

    def test_interpolate_string_param(self):
        """String parameters should be quoted and sanitized."""
        from self_service_queries.src.executor import AthenaExecutor

        sql = AthenaExecutor._interpolate(
            "SELECT * FROM t WHERE name = {{name}}",
            {"name": "test_value"},
        )

        assert sql == "SELECT * FROM t WHERE name = 'test_value'"

    def test_interpolate_date_param(self):
        """Date parameters should be properly quoted."""
        from self_service_queries.src.executor import AthenaExecutor

        sql = AthenaExecutor._interpolate(
            "SELECT * FROM t WHERE date = {{date}}",
            {"date": "2024-01-15"},
        )

        assert sql == "SELECT * FROM t WHERE date = '2024-01-15'"

    def test_interpolate_int_param(self):
        """Integer parameters should not be quoted."""
        from self_service_queries.src.executor import AthenaExecutor

        sql = AthenaExecutor._interpolate(
            "SELECT * FROM t LIMIT {{limit}}",
            {"limit": 100},
        )

        assert sql == "SELECT * FROM t LIMIT 100"

    def test_interpolate_rejects_sql_injection(self):
        """SQL injection attempts should be rejected."""
        from self_service_queries.src.executor import AthenaExecutor

        with pytest.raises(ValueError, match="invalid characters"):
            AthenaExecutor._interpolate(
                "SELECT * FROM t WHERE name = {{name}}",
                {"name": "'; DROP TABLE users; --"},
            )

    def test_interpolate_unresolved_placeholder(self):
        """Unresolved placeholders should raise an error."""
        from self_service_queries.src.executor import AthenaExecutor

        with pytest.raises(ValueError, match="Unresolved"):
            AthenaExecutor._interpolate(
                "SELECT * FROM t WHERE x = {{a}} AND y = {{b}}",
                {"a": "value"},
            )

    def test_interpolate_multiple_params(self):
        """Multiple parameters should all be resolved."""
        from self_service_queries.src.executor import AthenaExecutor

        sql = AthenaExecutor._interpolate(
            "SELECT * FROM t WHERE date >= {{start}} AND date <= {{end}} LIMIT {{n}}",
            {"start": "2024-01-01", "end": "2024-01-31", "n": 50},
        )

        assert "'2024-01-01'" in sql
        assert "'2024-01-31'" in sql
        assert "50" in sql


class TestHandler:
    """Test API handler routing."""

    @patch("self_service_queries.src.handler._get_template")
    @patch("self_service_queries.src.handler.AthenaExecutor")
    @patch("self_service_queries.src.handler.UsageTracker")
    def test_execute_query_missing_template(self, mock_tracker, mock_exec, mock_tmpl):
        """Should return 400 when template field is missing."""
        from self_service_queries.src.handler import handler

        result = handler(
            {
                "httpMethod": "POST",
                "path": "/query",
                "body": json.dumps({}),
                "requestContext": {"authorizer": {"claims": {}}},
            },
            None,
        )

        assert result["statusCode"] == 400

    def test_not_found_route(self):
        """Unknown routes should return 404."""
        from self_service_queries.src.handler import handler

        result = handler(
            {
                "httpMethod": "GET",
                "path": "/unknown",
                "body": "{}",
                "queryStringParameters": {},
                "requestContext": {"authorizer": {"claims": {}}},
            },
            None,
        )

        assert result["statusCode"] == 404
