"""
Quality Engine — Lambda Handler

Scheduled via EventBridge to run quality checks on all registered datasets.

Architecture:
  EventBridge (cron) → Lambda (this) → Athena queries → DynamoDB results → SNS alerts
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Any

import boto3

from .freshness import FreshnessChecker
from .volume import VolumeAnomalyDetector
from .null_monitor import NullRateMonitor

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")

RESULTS_TABLE = os.environ.get("RESULTS_TABLE", "data-quality-results")
ALERT_TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN", "")
DATASETS_TABLE = os.environ.get("DATASETS_TABLE", "data-quality-datasets")


def handler(event: dict, context: Any) -> dict:
    """Run quality checks for all registered datasets."""
    datasets = _get_registered_datasets()
    timestamp = datetime.now(timezone.utc).isoformat()

    all_results = []

    for dataset in datasets:
        logger.info("Running quality checks for '%s'", dataset["name"])

        result = {
            "dataset": dataset["name"],
            "timestamp": timestamp,
            "checks": {},
        }

        # 1. Freshness check
        freshness = FreshnessChecker(dataset)
        result["checks"]["freshness"] = freshness.check()

        # 2. Volume anomaly detection
        volume = VolumeAnomalyDetector(dataset)
        result["checks"]["volume"] = volume.check()

        # 3. Null rate monitoring
        null_monitor = NullRateMonitor(dataset)
        result["checks"]["null_rates"] = null_monitor.check()

        # Calculate overall score
        result["quality_score"] = _calculate_score(result["checks"])
        result["status"] = "healthy" if result["quality_score"] >= 0.8 else "degraded"

        # Store result
        _store_result(result)
        all_results.append(result)

        # Alert if degraded
        if result["status"] == "degraded":
            _send_alert(result)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "datasets_checked": len(all_results),
            "healthy": sum(1 for r in all_results if r["status"] == "healthy"),
            "degraded": sum(1 for r in all_results if r["status"] == "degraded"),
        }),
    }


def _get_registered_datasets() -> list[dict]:
    """Fetch registered datasets from DynamoDB."""
    table = dynamodb.Table(DATASETS_TABLE)
    response = table.scan()
    return response.get("Items", [])


def _calculate_score(checks: dict) -> float:
    """
    Calculate overall quality score (0.0 — 1.0).

    Weights:
      - Freshness: 30%
      - Volume: 30%
      - Null rates: 40%
    """
    weights = {"freshness": 0.30, "volume": 0.30, "null_rates": 0.40}
    score = 0.0

    for check_name, weight in weights.items():
        check = checks.get(check_name, {})
        if check.get("passed", False):
            score += weight
        elif check.get("score") is not None:
            score += weight * check["score"]

    return round(score, 3)


def _store_result(result: dict) -> None:
    """Store quality check result in DynamoDB."""
    table = dynamodb.Table(RESULTS_TABLE)
    table.put_item(Item={
        "dataset": result["dataset"],
        "timestamp": result["timestamp"],
        "quality_score": str(result["quality_score"]),
        "status": result["status"],
        "checks": json.dumps(result["checks"], default=str),
    })


def _send_alert(result: dict) -> None:
    """Send SNS alert for degraded datasets."""
    if not ALERT_TOPIC_ARN:
        return

    failed_checks = [
        name for name, check in result["checks"].items()
        if not check.get("passed", True)
    ]

    sns.publish(
        TopicArn=ALERT_TOPIC_ARN,
        Subject=f"Data Quality Alert: {result['dataset']} ({result['quality_score']:.0%})",
        Message=json.dumps({
            "dataset": result["dataset"],
            "quality_score": result["quality_score"],
            "status": result["status"],
            "failed_checks": failed_checks,
            "timestamp": result["timestamp"],
        }, indent=2),
    )
