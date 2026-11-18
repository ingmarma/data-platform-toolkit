"""
Self-Service Queries — API Gateway Lambda Handler

Exposes a REST API for teams to run pre-approved Athena queries
without needing direct AWS access or SQL knowledge.

Endpoints:
  POST /query          → Execute a named query with parameters
  GET  /query/{id}     → Check query execution status / get results
  GET  /queries        → List available query templates
  GET  /usage          → Query usage analytics
"""

import json
import os
import logging
from typing import Any

import boto3

from .executor import AthenaExecutor
from .analytics import UsageTracker

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TEMPLATES_TABLE = os.environ.get("TEMPLATES_TABLE", "query-templates")
RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET", "query-results")
WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "self-service")


def handler(event: dict, context: Any) -> dict:
    """API Gateway Lambda handler."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")
    body = json.loads(event.get("body", "{}") or "{}")
    query_params = event.get("queryStringParameters") or {}

    # Extract user identity from API Gateway authorizer
    request_context = event.get("requestContext", {})
    authorizer = request_context.get("authorizer", {})
    user = authorizer.get("claims", {}).get("email", "anonymous")

    tracker = UsageTracker()

    try:
        if method == "POST" and path == "/query":
            return _execute_query(body, user, tracker)
        elif method == "GET" and path.startswith("/query/"):
            query_id = path.split("/")[-1]
            return _get_results(query_id)
        elif method == "GET" and path == "/queries":
            return _list_templates()
        elif method == "GET" and path == "/usage":
            return _get_usage(query_params, tracker)
        else:
            return _response(404, {"error": "Not found"})

    except Exception as e:
        logger.error("Request failed: %s", e, exc_info=True)
        return _response(500, {"error": "Internal server error"})


def _execute_query(body: dict, user: str, tracker: UsageTracker) -> dict:
    """Execute a named query template with parameters."""
    template_name = body.get("template")
    parameters = body.get("parameters", {})

    if not template_name:
        return _response(400, {"error": "Missing 'template' field"})

    # Load template
    template = _get_template(template_name)
    if not template:
        return _response(404, {"error": f"Template '{template_name}' not found"})

    # Validate parameters
    required_params = template.get("required_parameters", [])
    missing = [p for p in required_params if p not in parameters]
    if missing:
        return _response(400, {
            "error": f"Missing required parameters: {', '.join(missing)}",
        })

    # Execute
    executor = AthenaExecutor(
        workgroup=WORKGROUP,
        results_bucket=RESULTS_BUCKET,
    )

    result = executor.execute(
        sql_template=template["sql"],
        parameters=parameters,
        database=template.get("database", "default"),
    )

    # Track usage
    tracker.track(
        user=user,
        template=template_name,
        query_execution_id=result.get("query_execution_id", ""),
    )

    return _response(202, {
        "query_execution_id": result.get("query_execution_id"),
        "status": "QUEUED",
        "message": f"Query '{template_name}' submitted",
    })


def _get_results(query_id: str) -> dict:
    """Get query execution status and results."""
    executor = AthenaExecutor(
        workgroup=WORKGROUP,
        results_bucket=RESULTS_BUCKET,
    )

    result = executor.get_status(query_id)

    if result["status"] == "SUCCEEDED":
        # Include result location for download
        result["results_url"] = executor.get_results_url(query_id)

    return _response(200, result)


def _list_templates() -> dict:
    """List available query templates."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TEMPLATES_TABLE)

    try:
        response = table.scan(
            ProjectionExpression="#n, description, required_parameters, category",
            ExpressionAttributeNames={"#n": "name"},
        )

        templates = sorted(
            response.get("Items", []),
            key=lambda t: t.get("category", ""),
        )

        return _response(200, {"templates": templates})

    except Exception as e:
        logger.error("Failed to list templates: %s", e)
        return _response(500, {"error": "Failed to load templates"})


def _get_usage(params: dict, tracker: UsageTracker) -> dict:
    """Get query usage analytics."""
    days = int(params.get("days", "7"))
    summary = tracker.get_summary(days=days)
    return _response(200, summary)


def _get_template(name: str) -> dict | None:
    """Load a query template from DynamoDB."""
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(TEMPLATES_TABLE)

    try:
        response = table.get_item(Key={"name": name})
        return response.get("Item")
    except Exception as e:
        logger.error("Failed to load template '%s': %s", name, e)
        return None


def _response(status: int, body: dict) -> dict:
    """Build API Gateway response."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
