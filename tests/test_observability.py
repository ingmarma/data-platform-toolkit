"""Tests for Pipeline Observability module."""

import json
import pytest
from unittest.mock import MagicMock, patch


class TestCostEstimator:
    """Test cost estimation calculations."""

    def test_glue_cost_basic(self):
        """Glue cost for 2 DPU, 1 hour."""
        from pipeline_observability.src.cost_estimator import CostEstimator

        estimator = CostEstimator()
        # 3600 seconds = 1 hour, 2 DPU
        cost = estimator.estimate_glue(dpu_seconds=3600, max_capacity=2)

        # 1 hour * 2 DPU * $0.44 = $0.88
        assert abs(cost - 0.88) < 0.01

    def test_glue_minimum_billing(self):
        """Glue should bill minimum 1 minute."""
        from pipeline_observability.src.cost_estimator import CostEstimator

        estimator = CostEstimator()
        cost_1s = estimator.estimate_glue(dpu_seconds=1, max_capacity=2)
        cost_60s = estimator.estimate_glue(dpu_seconds=60, max_capacity=2)

        # 1 second should be billed as 60 seconds
        assert cost_1s == cost_60s

    def test_athena_cost(self):
        """Athena: 1 TB scanned = $5."""
        from pipeline_observability.src.cost_estimator import CostEstimator

        estimator = CostEstimator()
        one_tb = 1024 ** 4
        cost = estimator.estimate_athena(bytes_scanned=one_tb)

        assert abs(cost - 5.0) < 0.01

    def test_athena_minimum_charge(self):
        """Athena has 10 MB minimum charge."""
        from pipeline_observability.src.cost_estimator import CostEstimator

        estimator = CostEstimator()
        cost_1b = estimator.estimate_athena(bytes_scanned=1)
        cost_10mb = estimator.estimate_athena(bytes_scanned=10 * 1024 * 1024)

        assert cost_1b == cost_10mb

    def test_lambda_cost(self):
        """Lambda cost calculation."""
        from pipeline_observability.src.cost_estimator import CostEstimator

        estimator = CostEstimator()
        cost = estimator.estimate_lambda(
            duration_ms=1000,
            memory_mb=1024,
            invocations=1,
        )

        # 1 GB-second * $0.0000166667 + $0.0000002
        assert cost > 0
        assert cost < 0.001

    def test_pipeline_run_total(self):
        """Full pipeline run should sum all services."""
        from pipeline_observability.src.cost_estimator import CostEstimator

        estimator = CostEstimator()
        result = estimator.estimate_pipeline_run(
            glue_dpu_seconds=3600,
            glue_max_capacity=2,
            athena_bytes_scanned=1024 ** 4,
            lambda_invocations=100,
            lambda_duration_ms=500,
            lambda_memory_mb=256,
        )

        assert "glue" in result
        assert "athena" in result
        assert "lambda" in result
        assert "total" in result
        assert result["total"] > 0
        assert abs(result["total"] - sum(
            v for k, v in result.items() if k != "total"
        )) < 0.000001


class TestMetricsCollector:
    """Test metrics collection."""

    @patch("pipeline_observability.src.metrics.boto3")
    def test_store_sanitizes_floats(self, mock_boto):
        """Floats should be converted to Decimal for DynamoDB."""
        from pipeline_observability.src.metrics import MetricsCollector

        collector = MetricsCollector.__new__(MetricsCollector)
        sanitized = collector._sanitize_for_dynamo({
            "cost": 1.234,
            "name": "test",
            "count": 42,
        })

        from decimal import Decimal
        assert isinstance(sanitized["cost"], Decimal)
        assert isinstance(sanitized["name"], str)
        assert isinstance(sanitized["count"], int)


class TestHandler:
    """Test Lambda handler routing."""

    @patch("pipeline_observability.src.handler.MetricsCollector")
    @patch("pipeline_observability.src.handler.CostEstimator")
    def test_unknown_source_ignored(self, mock_cost, mock_collector):
        """Unknown event sources should be ignored."""
        from pipeline_observability.src.handler import handler

        result = handler(
            {"source": "unknown.source", "detail-type": "test", "detail": {}},
            None,
        )

        assert result["statusCode"] == 200
        assert "ignored" in result["body"]
