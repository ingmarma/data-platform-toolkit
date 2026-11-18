"""
Schema Validator — Lambda Handler

Triggered by S3 PutObject events. Validates incoming data files
against registered schemas before they enter the pipeline.

Architecture:
  S3 Event → Lambda (this) → Glue Schema Registry → Pass/Reject
"""

import json
import os
import logging
from typing import Any

import boto3

from .validator import SchemaValidator
from .breaking_changes import BreakingChangeDetector

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3 = boto3.client("s3")
sns = boto3.client("sns")

ALERT_TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN", "")
QUARANTINE_BUCKET = os.environ.get("QUARANTINE_BUCKET", "")
SCHEMA_REGISTRY = os.environ.get("SCHEMA_REGISTRY", "data-platform-schemas")


def handler(event: dict, context: Any) -> dict:
    """Process S3 events and validate schemas."""
    results = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        logger.info("Validating s3://%s/%s", bucket, key)

        try:
            result = _validate_object(bucket, key)
            results.append(result)

            if not result["valid"]:
                _handle_invalid(bucket, key, result)

        except Exception as e:
            logger.error("Validation failed for %s/%s: %s", bucket, key, e)
            results.append({
                "bucket": bucket,
                "key": key,
                "valid": False,
                "error": str(e),
            })

    return {
        "statusCode": 200,
        "body": json.dumps({
            "validated": len(results),
            "passed": sum(1 for r in results if r.get("valid")),
            "failed": sum(1 for r in results if not r.get("valid")),
            "results": results,
        }),
    }


def _validate_object(bucket: str, key: str) -> dict:
    """Validate a single S3 object against its registered schema."""
    # Determine dataset from key prefix: raw/{dataset}/{file}
    parts = key.split("/")
    if len(parts) < 2:
        return {"bucket": bucket, "key": key, "valid": True, "reason": "no_schema_prefix"}

    dataset = parts[1] if parts[0] == "raw" else parts[0]

    # Get the object
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read()

    # Determine format from extension
    if key.endswith(".json") or key.endswith(".jsonl"):
        data = _parse_json(body)
    elif key.endswith(".csv"):
        data = _parse_csv_header(body)
    else:
        return {"bucket": bucket, "key": key, "valid": True, "reason": "unsupported_format"}

    # Validate against schema
    validator = SchemaValidator(registry_name=SCHEMA_REGISTRY)
    validation_result = validator.validate(dataset, data)

    # Check for breaking changes if schema version changed
    if validation_result.get("schema_version_changed"):
        detector = BreakingChangeDetector(registry_name=SCHEMA_REGISTRY)
        breaking = detector.detect(
            dataset,
            validation_result["previous_version"],
            validation_result["current_version"],
        )
        validation_result["breaking_changes"] = breaking

    return {
        "bucket": bucket,
        "key": key,
        **validation_result,
    }


def _parse_json(body: bytes) -> list[dict]:
    """Parse JSON or JSONL content."""
    text = body.decode("utf-8").strip()
    # JSONL: one JSON object per line
    if "\n" in text and not text.startswith("["):
        return [json.loads(line) for line in text.split("\n") if line.strip()]
    # Regular JSON
    parsed = json.loads(text)
    return parsed if isinstance(parsed, list) else [parsed]


def _parse_csv_header(body: bytes) -> list[dict]:
    """Extract header from CSV to validate field names."""
    text = body.decode("utf-8")
    header_line = text.split("\n")[0].strip()
    fields = [f.strip().strip('"') for f in header_line.split(",")]
    return [{"_csv_fields": fields}]


def _handle_invalid(bucket: str, key: str, result: dict) -> None:
    """Move invalid files to quarantine and alert."""
    # Move to quarantine bucket
    if QUARANTINE_BUCKET:
        s3.copy_object(
            Bucket=QUARANTINE_BUCKET,
            Key=f"quarantine/{key}",
            CopySource={"Bucket": bucket, "Key": key},
        )
        s3.delete_object(Bucket=bucket, Key=key)
        logger.info("Moved %s to quarantine", key)

    # Send alert
    if ALERT_TOPIC_ARN:
        sns.publish(
            TopicArn=ALERT_TOPIC_ARN,
            Subject=f"Schema Validation Failed: {key}",
            Message=json.dumps(result, indent=2, default=str),
        )
