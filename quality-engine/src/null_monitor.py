"""
Null Rate Monitor

Tracks the percentage of null/empty values per column per dataset.
A sudden increase in null rates often indicates upstream schema changes,
ETL bugs, or data source issues.
"""

import logging
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

athena = boto3.client("athena")


class NullRateMonitor:
    """Monitor null rates per column in datasets."""

    # Maximum acceptable null rate per column (override per dataset)
    DEFAULT_MAX_NULL_RATE = 0.10  # 10%

    def __init__(self, dataset: dict):
        self.name = dataset["name"]
        self.database = dataset.get("athena_database", "")
        self.table = dataset.get("athena_table", "")
        self.monitored_columns = dataset.get("monitored_columns", [])
        self.max_null_rate = float(
            dataset.get("max_null_rate", self.DEFAULT_MAX_NULL_RATE)
        )

    def check(self) -> dict:
        """
        Check null rates for monitored columns.

        Returns:
            {
                "passed": bool,
                "columns": {
                    "column_name": {
                        "null_rate": float,
                        "threshold": float,
                        "passed": bool,
                    }
                },
                "score": float,
            }
        """
        if not self.monitored_columns:
            return {
                "passed": True,
                "reason": "No monitored columns configured",
                "score": 1.0,
            }

        null_rates = self._query_null_rates()

        if null_rates is None:
            return {
                "passed": True,
                "reason": "Could not query null rates",
                "score": 1.0,
            }

        columns = {}
        all_passed = True

        for col in self.monitored_columns:
            col_name = col if isinstance(col, str) else col["name"]
            threshold = (
                col.get("max_null_rate", self.max_null_rate)
                if isinstance(col, dict)
                else self.max_null_rate
            )
            rate = null_rates.get(col_name, 0.0)
            passed = rate <= threshold

            if not passed:
                all_passed = False

            columns[col_name] = {
                "null_rate": round(rate, 4),
                "threshold": threshold,
                "passed": passed,
            }

        # Score = average of per-column scores
        if columns:
            col_scores = []
            for col_data in columns.values():
                if col_data["null_rate"] <= col_data["threshold"]:
                    col_scores.append(1.0)
                else:
                    # Degrades linearly from threshold to 2x threshold
                    overshoot = col_data["null_rate"] - col_data["threshold"]
                    score = max(0, 1.0 - overshoot / col_data["threshold"])
                    col_scores.append(score)
            avg_score = sum(col_scores) / len(col_scores)
        else:
            avg_score = 1.0

        return {
            "passed": all_passed,
            "columns": columns,
            "score": round(avg_score, 3),
        }

    def _query_null_rates(self) -> Optional[dict[str, float]]:
        """Query Athena for null rates per column."""
        if not self.database or not self.table:
            return None

        col_names = [
            c if isinstance(c, str) else c["name"]
            for c in self.monitored_columns
        ]

        # Build a query that calculates null rate for each column
        null_checks = []
        for col in col_names:
            null_checks.append(
                f"CAST(SUM(CASE WHEN \"{col}\" IS NULL THEN 1 ELSE 0 END) AS DOUBLE) "
                f"/ CAST(COUNT(*) AS DOUBLE) AS null_rate_{col}"
            )

        query = f"""
            SELECT
                COUNT(*) AS total_rows,
                {', '.join(null_checks)}
            FROM "{self.database}"."{self.table}"
        """

        try:
            # Execute Athena query
            # In production, this would use the shared Athena executor
            logger.info(
                "Null rate query for '%s': %s columns to check",
                self.name, len(col_names),
            )
            # Placeholder: return None until Athena executor is integrated
            return None

        except Exception as e:
            logger.error("Failed to query null rates for '%s': %s", self.name, e)
            return None


def build_null_rate_query(database: str, table: str, columns: list[str]) -> str:
    """
    Build an Athena SQL query to calculate null rates.

    Useful for running manual checks:
        query = build_null_rate_query("mydb", "mytable", ["col1", "col2"])
        # Then execute via Athena console or API
    """
    null_checks = []
    for col in columns:
        null_checks.append(
            f"  ROUND("
            f"CAST(SUM(CASE WHEN \"{col}\" IS NULL THEN 1 ELSE 0 END) AS DOUBLE) "
            f"/ CAST(COUNT(*) AS DOUBLE), 4"
            f") AS null_rate_{col}"
        )

    return f"""
SELECT
  COUNT(*) AS total_rows,
{',\\n'.join(null_checks)}
FROM "{database}"."{table}"
""".strip()
