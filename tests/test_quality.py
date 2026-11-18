"""Tests for Quality Engine module."""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal


class TestFreshnessChecker:
    """Test data freshness checks."""

    def test_fresh_data_passes(self):
        """Data within SLA should pass."""
        from quality_engine.src.freshness import FreshnessChecker
        from datetime import datetime, timezone, timedelta

        checker = FreshnessChecker({
            "name": "test_dataset",
            "freshness_sla_minutes": 60,
        })

        # Mock: last updated 30 minutes ago
        last_modified = datetime.now(timezone.utc) - timedelta(minutes=30)

        with patch.object(checker, "_get_last_modified", return_value=last_modified):
            result = checker.check()

        assert result["passed"] is True
        assert result["score"] == 1.0
        assert result["minutes_since_update"] <= 31

    def test_stale_data_fails(self):
        """Data beyond SLA should fail."""
        from quality_engine.src.freshness import FreshnessChecker
        from datetime import datetime, timezone, timedelta

        checker = FreshnessChecker({
            "name": "test_dataset",
            "freshness_sla_minutes": 60,
        })

        # Mock: last updated 90 minutes ago (1.5x SLA)
        last_modified = datetime.now(timezone.utc) - timedelta(minutes=90)

        with patch.object(checker, "_get_last_modified", return_value=last_modified):
            result = checker.check()

        assert result["passed"] is False
        assert 0.0 < result["score"] < 1.0

    def test_score_degrades_linearly(self):
        """Score should degrade from 1.0 at SLA to 0.0 at 2x SLA."""
        from quality_engine.src.freshness import FreshnessChecker
        from datetime import datetime, timezone, timedelta

        checker = FreshnessChecker({
            "name": "test",
            "freshness_sla_minutes": 100,
        })

        # At exactly 2x SLA (200 min), score should be 0.0
        last_modified = datetime.now(timezone.utc) - timedelta(minutes=200)

        with patch.object(checker, "_get_last_modified", return_value=last_modified):
            result = checker.check()

        assert result["score"] == 0.0

    def test_no_data_returns_zero_score(self):
        """Unable to determine last update should return score 0."""
        from quality_engine.src.freshness import FreshnessChecker

        checker = FreshnessChecker({"name": "test"})

        with patch.object(checker, "_get_last_modified", return_value=None):
            result = checker.check()

        assert result["passed"] is False
        assert result["score"] == 0.0


class TestVolumeAnomalyDetector:
    """Test volume anomaly detection."""

    def test_normal_volume_passes(self):
        """Volume within thresholds should pass."""
        from quality_engine.src.volume import VolumeAnomalyDetector

        detector = VolumeAnomalyDetector({"name": "test"})

        with patch.object(detector, "_get_current_volume", return_value=1000):
            with patch.object(detector, "_get_historical_volumes",
                              return_value=[900, 1100, 1050, 950, 1000, 980, 1020]):
                with patch.object(detector, "_store_volume"):
                    result = detector.check()

        assert result["passed"] is True
        assert result["anomaly_type"] is None

    def test_volume_drop_detected(self):
        """50%+ drop from average should trigger alert."""
        from quality_engine.src.volume import VolumeAnomalyDetector

        detector = VolumeAnomalyDetector({"name": "test"})

        with patch.object(detector, "_get_current_volume", return_value=200):
            with patch.object(detector, "_get_historical_volumes",
                              return_value=[1000, 1000, 1000, 1000, 1000, 1000, 1000]):
                with patch.object(detector, "_store_volume"):
                    result = detector.check()

        assert result["passed"] is False
        assert result["anomaly_type"] == "drop"

    def test_volume_spike_detected(self):
        """3x+ above average should trigger alert."""
        from quality_engine.src.volume import VolumeAnomalyDetector

        detector = VolumeAnomalyDetector({"name": "test"})

        with patch.object(detector, "_get_current_volume", return_value=5000):
            with patch.object(detector, "_get_historical_volumes",
                              return_value=[1000, 1000, 1000, 1000, 1000, 1000, 1000]):
                with patch.object(detector, "_store_volume"):
                    result = detector.check()

        assert result["passed"] is False
        assert result["anomaly_type"] == "spike"


class TestNullRateMonitor:
    """Test null rate monitoring."""

    def test_no_columns_configured_passes(self):
        """No monitored columns should return passed with score 1.0."""
        from quality_engine.src.null_monitor import NullRateMonitor

        monitor = NullRateMonitor({
            "name": "test",
            "monitored_columns": [],
        })

        result = monitor.check()
        assert result["passed"] is True
        assert result["score"] == 1.0

    def test_build_null_rate_query(self):
        """Should generate valid Athena SQL."""
        from quality_engine.src.null_monitor import build_null_rate_query

        sql = build_null_rate_query("mydb", "users", ["email", "phone"])

        assert '"mydb"."users"' in sql
        assert "null_rate_email" in sql
        assert "null_rate_phone" in sql
        assert "COUNT(*)" in sql
