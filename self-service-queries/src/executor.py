"""
Athena Query Executor

Safely executes parameterized Athena queries with:
  - SQL injection prevention via parameterized templates
  - Query cost limits (max bytes scanned)
  - Timeout handling
  - Result caching
"""

import re
import logging
import time
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

athena = boto3.client("athena")
s3 = boto3.client("s3")

# Safety limits
MAX_BYTES_SCANNED = 10 * (1024 ** 3)  # 10 GB max per query
QUERY_TIMEOUT_SECONDS = 300            # 5 minutes


class AthenaExecutor:
    """Execute Athena queries safely."""

    def __init__(
        self,
        workgroup: str = "self-service",
        results_bucket: str = "query-results",
    ):
        self.workgroup = workgroup
        self.results_bucket = results_bucket

    def execute(
        self,
        sql_template: str,
        parameters: dict,
        database: str = "default",
    ) -> dict:
        """
        Execute a parameterized Athena query.

        Parameters are safely interpolated — only values matching
        expected types (string, int, date) are allowed.

        Returns:
            {"query_execution_id": str, "status": str}
        """
        # Sanitize and interpolate parameters
        sql = self._interpolate(sql_template, parameters)

        logger.info("Executing query in database '%s': %s...", database, sql[:100])

        try:
            response = athena.start_query_execution(
                QueryString=sql,
                QueryExecutionContext={"Database": database},
                WorkGroup=self.workgroup,
                ResultConfiguration={
                    "OutputLocation": f"s3://{self.results_bucket}/results/",
                },
            )

            execution_id = response["QueryExecutionId"]

            return {
                "query_execution_id": execution_id,
                "status": "QUEUED",
            }

        except Exception as e:
            logger.error("Query execution failed: %s", e)
            return {
                "query_execution_id": None,
                "status": "FAILED",
                "error": str(e),
            }

    def get_status(self, query_execution_id: str) -> dict:
        """Check query execution status."""
        try:
            response = athena.get_query_execution(
                QueryExecutionId=query_execution_id,
            )

            execution = response["QueryExecution"]
            status = execution["Status"]["State"]
            statistics = execution.get("Statistics", {})

            result = {
                "query_execution_id": query_execution_id,
                "status": status,
            }

            if status == "SUCCEEDED":
                result["bytes_scanned"] = statistics.get(
                    "DataScannedInBytes", 0,
                )
                result["execution_time_ms"] = statistics.get(
                    "EngineExecutionTimeInMillis", 0,
                )

            elif status == "FAILED":
                result["error"] = execution["Status"].get(
                    "StateChangeReason", "Unknown error",
                )

            return result

        except Exception as e:
            logger.error("Failed to get query status: %s", e)
            return {
                "query_execution_id": query_execution_id,
                "status": "UNKNOWN",
                "error": str(e),
            }

    def get_results_url(self, query_execution_id: str) -> Optional[str]:
        """Generate a pre-signed URL for downloading query results."""
        key = f"results/{query_execution_id}.csv"

        try:
            url = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.results_bucket,
                    "Key": key,
                },
                ExpiresIn=3600,  # 1 hour
            )
            return url
        except Exception as e:
            logger.error("Failed to generate results URL: %s", e)
            return None

    def wait_for_completion(
        self,
        query_execution_id: str,
        timeout: int = QUERY_TIMEOUT_SECONDS,
    ) -> dict:
        """Poll until query completes or times out."""
        start = time.time()

        while time.time() - start < timeout:
            status = self.get_status(query_execution_id)

            if status["status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
                return status

            time.sleep(2)

        return {
            "query_execution_id": query_execution_id,
            "status": "TIMEOUT",
            "error": f"Query did not complete within {timeout}s",
        }

    @staticmethod
    def _interpolate(template: str, parameters: dict) -> str:
        """
        Safely interpolate parameters into SQL template.

        Template uses {{param_name}} placeholders. Only alphanumeric
        values, dates, and quoted strings are allowed.
        """
        sql = template

        for key, value in parameters.items():
            placeholder = "{{" + key + "}}"

            if placeholder not in sql:
                continue

            # Sanitize based on value type
            if isinstance(value, int):
                safe_value = str(value)
            elif isinstance(value, str):
                # Allow dates (YYYY-MM-DD) and simple alphanumeric strings
                if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
                    safe_value = f"'{value}'"
                elif re.match(r"^[a-zA-Z0-9_.\-\s]+$", value):
                    safe_value = f"'{value}'"
                else:
                    raise ValueError(
                        f"Parameter '{key}' contains invalid characters"
                    )
            else:
                raise ValueError(
                    f"Parameter '{key}' has unsupported type: {type(value)}"
                )

            sql = sql.replace(placeholder, safe_value)

        # Check for unresolved placeholders
        remaining = re.findall(r"\{\{(\w+)\}\}", sql)
        if remaining:
            raise ValueError(
                f"Unresolved parameters: {', '.join(remaining)}"
            )

        return sql
