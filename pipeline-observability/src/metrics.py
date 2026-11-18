"""
Metrics Collector

Stores pipeline execution metrics in DynamoDB and publishes
key indicators to CloudWatch for dashboarding and alarms.
"""

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3

logger = logging.getLogger(__name__)

NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "DataPlatform/Pipelines")


class MetricsCollector:
    """Collect, store, and publish pipeline metrics."""

    def __init__(self, table_name: str = "pipeline-metrics"):
        self.dynamodb = boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(table_name)
        self.cloudwatch = boto3.client("cloudwatch")

    def store(self, metrics: dict) -> None:
        """Store pipeline run metrics in DynamoDB."""
        pipeline = metrics.get("pipeline_name", "unknown")
        run_id = metrics.get("run_id", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        item = {
            "pipeline_name": pipeline,
            "run_id": run_id,
            "timestamp": now,
            **self._sanitize_for_dynamo(metrics),
        }

        try:
            self.table.put_item(Item=item)
            logger.info("Stored metrics for %s/%s", pipeline, run_id)
        except Exception as e:
            logger.error("Failed to store metrics: %s", e)

    def publish_cloudwatch(self, metrics: dict) -> None:
        """Publish key metrics to CloudWatch."""
        pipeline = metrics.get("pipeline_name", "unknown")
        status = metrics.get("status", "unknown")

        metric_data = [
            {
                "MetricName": "PipelineExecution",
                "Dimensions": [
                    {"Name": "Pipeline", "Value": pipeline},
                    {"Name": "Status", "Value": status},
                ],
                "Value": 1,
                "Unit": "Count",
            },
        ]

        # Duration metric (only for completed runs)
        if "duration_seconds" in metrics:
            metric_data.append({
                "MetricName": "ExecutionDuration",
                "Dimensions": [
                    {"Name": "Pipeline", "Value": pipeline},
                ],
                "Value": float(metrics["duration_seconds"]),
                "Unit": "Seconds",
            })

        # Cost metric
        if "estimated_cost_usd" in metrics:
            metric_data.append({
                "MetricName": "EstimatedCost",
                "Dimensions": [
                    {"Name": "Pipeline", "Value": pipeline},
                ],
                "Value": float(metrics["estimated_cost_usd"]),
                "Unit": "None",
            })

        # Records processed
        if "records_out" in metrics:
            metric_data.append({
                "MetricName": "RecordsProcessed",
                "Dimensions": [
                    {"Name": "Pipeline", "Value": pipeline},
                ],
                "Value": float(metrics["records_out"]),
                "Unit": "Count",
            })

        try:
            self.cloudwatch.put_metric_data(
                Namespace=NAMESPACE,
                MetricData=metric_data,
            )
            logger.info("Published %d metrics for %s", len(metric_data), pipeline)
        except Exception as e:
            logger.error("Failed to publish CloudWatch metrics: %s", e)

    def query_history(
        self, pipeline_name: str, limit: int = 50,
    ) -> list[dict]:
        """Query execution history for a pipeline."""
        try:
            response = self.table.query(
                KeyConditionExpression="pipeline_name = :name",
                ExpressionAttributeValues={":name": pipeline_name},
                ScanIndexForward=False,
                Limit=limit,
            )
            return response.get("Items", [])
        except Exception as e:
            logger.error("Failed to query history: %s", e)
            return []

    def get_summary(self, pipeline_name: str, days: int = 7) -> dict:
        """Get execution summary for the last N days."""
        history = self.query_history(pipeline_name, limit=200)

        if not history:
            return {"pipeline": pipeline_name, "runs": 0}

        succeeded = [r for r in history if r.get("status") == "succeeded"]
        failed = [r for r in history if r.get("status") == "failed"]

        durations = [
            float(r["duration_seconds"])
            for r in succeeded
            if "duration_seconds" in r
        ]

        costs = [
            float(r["estimated_cost_usd"])
            for r in history
            if "estimated_cost_usd" in r
        ]

        return {
            "pipeline": pipeline_name,
            "runs": len(history),
            "succeeded": len(succeeded),
            "failed": len(failed),
            "success_rate": (
                round(len(succeeded) / len(history), 3) if history else 0
            ),
            "avg_duration_seconds": (
                round(sum(durations) / len(durations), 1) if durations else None
            ),
            "total_cost_usd": round(sum(costs), 4) if costs else 0,
        }

    @staticmethod
    def _sanitize_for_dynamo(data: dict) -> dict:
        """Convert floats to Decimal for DynamoDB compatibility."""
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, float):
                sanitized[k] = Decimal(str(round(v, 6)))
            elif isinstance(v, dict):
                sanitized[k] = MetricsCollector._sanitize_for_dynamo(v)
            else:
                sanitized[k] = v
        return sanitized
