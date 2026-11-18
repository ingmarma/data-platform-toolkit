"""
Pipeline Observability — Lambda Handler

Consumes pipeline execution events via EventBridge and stores
metrics for dashboarding and alerting.

Architecture:
  Glue Job/Step Function → EventBridge → Lambda (this) → DynamoDB + CloudWatch
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Any

import boto3

from .metrics import MetricsCollector
from .cost_estimator import CostEstimator

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

METRICS_TABLE = os.environ.get("METRICS_TABLE", "pipeline-metrics")


def handler(event: dict, context: Any) -> dict:
    """Process pipeline execution events."""
    source = event.get("source", "")
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})

    logger.info("Received event: source=%s, type=%s", source, detail_type)

    collector = MetricsCollector(table_name=METRICS_TABLE)
    cost_estimator = CostEstimator()

    # Route based on event source
    if source == "aws.glue":
        return _handle_glue_event(detail, detail_type, collector, cost_estimator)
    elif source == "aws.states":
        return _handle_step_function_event(detail, detail_type, collector)
    elif source == "custom.pipeline":
        return _handle_custom_event(detail, collector, cost_estimator)
    else:
        logger.warning("Unknown event source: %s", source)
        return {"statusCode": 200, "body": "ignored"}


def _handle_glue_event(
    detail: dict, detail_type: str,
    collector: MetricsCollector, cost_estimator: CostEstimator,
) -> dict:
    """Handle AWS Glue job state change events."""
    job_name = detail.get("jobName", "unknown")
    state = detail.get("state", "")
    job_run_id = detail.get("jobRunId", "")

    if state == "SUCCEEDED":
        # Calculate metrics
        started = detail.get("startedOn", "")
        completed = detail.get("completedOn", "")
        dpu_seconds = detail.get("executionTime", 0)
        max_capacity = detail.get("maxCapacity", 2)

        # Estimate cost
        cost = cost_estimator.estimate_glue(
            dpu_seconds=dpu_seconds,
            max_capacity=max_capacity,
        )

        metrics = {
            "pipeline_name": job_name,
            "run_id": job_run_id,
            "status": "succeeded",
            "started_at": started,
            "completed_at": completed,
            "duration_seconds": dpu_seconds,
            "estimated_cost_usd": cost,
        }

        collector.store(metrics)
        collector.publish_cloudwatch(metrics)

        return {"statusCode": 200, "body": json.dumps(metrics, default=str)}

    elif state == "FAILED":
        metrics = {
            "pipeline_name": job_name,
            "run_id": job_run_id,
            "status": "failed",
            "error": detail.get("message", "Unknown error"),
        }
        collector.store(metrics)
        collector.publish_cloudwatch(metrics)

        return {"statusCode": 200, "body": json.dumps(metrics, default=str)}

    return {"statusCode": 200, "body": "ignored"}


def _handle_step_function_event(
    detail: dict, detail_type: str, collector: MetricsCollector,
) -> dict:
    """Handle Step Functions state change events."""
    execution_arn = detail.get("executionArn", "")
    status = detail.get("status", "")
    name = detail.get("stateMachineArn", "").split(":")[-1]

    if status in ("SUCCEEDED", "FAILED", "TIMED_OUT"):
        started = detail.get("startDate", "")
        stopped = detail.get("stopDate", "")

        metrics = {
            "pipeline_name": name,
            "run_id": execution_arn.split(":")[-1],
            "status": status.lower(),
            "started_at": started,
            "completed_at": stopped,
        }

        collector.store(metrics)
        collector.publish_cloudwatch(metrics)

        return {"statusCode": 200, "body": json.dumps(metrics, default=str)}

    return {"statusCode": 200, "body": "ignored"}


def _handle_custom_event(
    detail: dict, collector: MetricsCollector, cost_estimator: CostEstimator,
) -> dict:
    """
    Handle custom pipeline events.

    Expected format:
    {
        "pipeline_name": str,
        "run_id": str,
        "stage": str,
        "records_in": int,
        "records_out": int,
        "records_rejected": int,
        "duration_seconds": float,
        "athena_bytes_scanned": int (optional),
    }
    """
    # Estimate cost if Athena bytes provided
    if "athena_bytes_scanned" in detail:
        detail["estimated_cost_usd"] = cost_estimator.estimate_athena(
            bytes_scanned=detail["athena_bytes_scanned"]
        )

    collector.store(detail)
    collector.publish_cloudwatch(detail)

    return {"statusCode": 200, "body": json.dumps(detail, default=str)}
