"""
Freshness Checker

Monitors whether datasets are updated within their defined SLA windows.
A dataset with a 1-hour freshness SLA should have new data every hour.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

s3 = boto3.client("s3")
athena = boto3.client("athena")


class FreshnessChecker:
    """Check if a dataset is fresh according to its SLA."""

    def __init__(self, dataset: dict):
        """
        Args:
            dataset: {
                "name": str,
                "s3_path": str,              # e.g., "s3://bucket/prefix/"
                "freshness_sla_minutes": int, # e.g., 60
                "athena_database": str,
                "athena_table": str,
            }
        """
        self.name = dataset["name"]
        self.s3_path = dataset.get("s3_path", "")
        self.sla_minutes = int(dataset.get("freshness_sla_minutes", 1440))  # default: 24h
        self.database = dataset.get("athena_database", "")
        self.table = dataset.get("athena_table", "")

    def check(self) -> dict:
        """
        Check data freshness.

        Returns:
            {
                "passed": bool,
                "last_updated": str (ISO),
                "sla_minutes": int,
                "minutes_since_update": int,
                "score": float (0-1),
            }
        """
        last_updated = self._get_last_modified()

        if not last_updated:
            return {
                "passed": False,
                "last_updated": None,
                "sla_minutes": self.sla_minutes,
                "minutes_since_update": None,
                "score": 0.0,
                "reason": "Could not determine last update time",
            }

        now = datetime.now(timezone.utc)
        delta = now - last_updated
        minutes_since = int(delta.total_seconds() / 60)

        passed = minutes_since <= self.sla_minutes

        # Score degrades linearly: at SLA = 1.0, at 2x SLA = 0.0
        if minutes_since <= self.sla_minutes:
            score = 1.0
        elif minutes_since >= self.sla_minutes * 2:
            score = 0.0
        else:
            score = 1.0 - (minutes_since - self.sla_minutes) / self.sla_minutes

        return {
            "passed": passed,
            "last_updated": last_updated.isoformat(),
            "sla_minutes": self.sla_minutes,
            "minutes_since_update": minutes_since,
            "score": round(score, 3),
        }

    def _get_last_modified(self) -> Optional[datetime]:
        """Get the most recent modification time for the dataset."""
        # Try S3 listing first (faster)
        if self.s3_path:
            return self._last_modified_s3()

        # Fall back to Athena partition query
        if self.database and self.table:
            return self._last_modified_athena()

        return None

    def _last_modified_s3(self) -> Optional[datetime]:
        """Get latest S3 object modification time."""
        try:
            parts = self.s3_path.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""

            response = s3.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=10,
            )

            if "Contents" not in response:
                return None

            # Sort by LastModified descending
            objects = sorted(
                response["Contents"],
                key=lambda x: x["LastModified"],
                reverse=True,
            )
            return objects[0]["LastModified"]

        except Exception as e:
            logger.error("Failed to check S3 freshness for '%s': %s", self.name, e)
            return None

    def _last_modified_athena(self) -> Optional[datetime]:
        """Query Athena for the latest partition or timestamp."""
        try:
            query = f"""
                SELECT MAX(update_timestamp) as last_update
                FROM "{self.database}"."{self.table}"
            """
            # Note: in production, use the Athena executor from self-service-queries
            # This is a simplified check
            logger.info("Athena freshness check not implemented for '%s'", self.name)
            return None

        except Exception as e:
            logger.error("Failed Athena freshness check for '%s': %s", self.name, e)
            return None
