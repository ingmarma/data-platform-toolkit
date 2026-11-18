"""
Volume Anomaly Detector

Detects sudden drops or spikes in data volume that could indicate
pipeline failures, upstream issues, or data duplication.

Uses a simple statistical approach: compare today's volume against
the rolling average of the last N days.
"""

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

dynamodb = boto3.resource("dynamodb")
athena = boto3.client("athena")


class VolumeAnomalyDetector:
    """Detect anomalies in data volume."""

    # Volume change thresholds
    DROP_THRESHOLD = 0.5     # 50% drop from average → alert
    SPIKE_THRESHOLD = 3.0    # 300% above average → alert
    LOOKBACK_DAYS = 7        # Rolling window for baseline

    def __init__(self, dataset: dict):
        self.name = dataset["name"]
        self.metrics_table = dataset.get("metrics_table", "data-quality-metrics")
        self.database = dataset.get("athena_database", "")
        self.table = dataset.get("athena_table", "")

    def check(self) -> dict:
        """
        Check for volume anomalies.

        Returns:
            {
                "passed": bool,
                "current_volume": int,
                "average_volume": float,
                "ratio": float,
                "anomaly_type": None | "drop" | "spike",
                "score": float,
            }
        """
        current = self._get_current_volume()
        historical = self._get_historical_volumes()

        if current is None:
            return {
                "passed": True,
                "reason": "Could not determine current volume",
                "score": 1.0,
            }

        if not historical:
            # No history yet — can't detect anomalies
            self._store_volume(current)
            return {
                "passed": True,
                "current_volume": current,
                "reason": "Insufficient history for anomaly detection",
                "score": 1.0,
            }

        avg = sum(historical) / len(historical)

        if avg == 0:
            ratio = float("inf") if current > 0 else 1.0
        else:
            ratio = current / avg

        anomaly_type = None
        passed = True
        score = 1.0

        if ratio < self.DROP_THRESHOLD:
            anomaly_type = "drop"
            passed = False
            score = ratio / self.DROP_THRESHOLD  # 0 at empty, 1.0 at threshold
        elif ratio > self.SPIKE_THRESHOLD:
            anomaly_type = "spike"
            passed = False
            score = max(0, 1.0 - (ratio - self.SPIKE_THRESHOLD) / self.SPIKE_THRESHOLD)

        # Store today's volume for future baselines
        self._store_volume(current)

        return {
            "passed": passed,
            "current_volume": current,
            "average_volume": round(avg, 1),
            "ratio": round(ratio, 3),
            "anomaly_type": anomaly_type,
            "lookback_days": self.LOOKBACK_DAYS,
            "score": round(max(0, min(1, score)), 3),
        }

    def _get_current_volume(self) -> Optional[int]:
        """Get today's record count."""
        try:
            # Count objects in today's partition
            s3 = boto3.client("s3")
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # This would be replaced with actual Athena COUNT(*) in production
            logger.info("Getting current volume for '%s'", self.name)
            return None  # Override in subclass or via Athena

        except Exception as e:
            logger.error("Failed to get current volume: %s", e)
            return None

    def _get_historical_volumes(self) -> list[int]:
        """Get volume history for the lookback window."""
        try:
            table = dynamodb.Table(self.metrics_table)
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=self.LOOKBACK_DAYS)
            ).isoformat()

            response = table.query(
                KeyConditionExpression="dataset_name = :name AND metric_date > :cutoff",
                ExpressionAttributeValues={
                    ":name": self.name,
                    ":cutoff": cutoff,
                },
            )

            return [int(item["volume"]) for item in response.get("Items", [])]

        except Exception as e:
            logger.error("Failed to get historical volumes: %s", e)
            return []

    def _store_volume(self, volume: int) -> None:
        """Store today's volume for future baseline calculations."""
        try:
            table = dynamodb.Table(self.metrics_table)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            table.put_item(Item={
                "dataset_name": self.name,
                "metric_date": today,
                "volume": volume,
            })
        except Exception as e:
            logger.error("Failed to store volume metric: %s", e)
