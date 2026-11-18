"""
Usage Analytics

Tracks who runs what queries and how often. Helps platform teams
understand adoption and optimize the most-used templates.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from collections import Counter

import boto3

logger = logging.getLogger(__name__)

USAGE_TABLE = os.environ.get("USAGE_TABLE", "query-usage")


class UsageTracker:
    """Track and analyze query usage patterns."""

    def __init__(self, table_name: str = USAGE_TABLE):
        self.dynamodb = boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(table_name)

    def track(
        self,
        user: str,
        template: str,
        query_execution_id: str = "",
    ) -> None:
        """Record a query execution event."""
        now = datetime.now(timezone.utc)

        item = {
            "user": user,
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "template": template,
            "query_execution_id": query_execution_id,
        }

        try:
            self.table.put_item(Item=item)
        except Exception as e:
            logger.error("Failed to track usage: %s", e)

    def get_summary(self, days: int = 7) -> dict:
        """
        Get usage summary for the last N days.

        Returns:
            {
                "period_days": int,
                "total_queries": int,
                "unique_users": int,
                "top_templates": [{"name": str, "count": int}],
                "top_users": [{"user": str, "count": int}],
                "daily_counts": [{"date": str, "count": int}],
            }
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        try:
            # Scan with date filter
            # Note: in production, use a GSI on 'date' for efficiency
            response = self.table.scan(
                FilterExpression="timestamp > :cutoff",
                ExpressionAttributeValues={":cutoff": cutoff},
            )

            items = response.get("Items", [])

            if not items:
                return {
                    "period_days": days,
                    "total_queries": 0,
                    "unique_users": 0,
                    "top_templates": [],
                    "top_users": [],
                    "daily_counts": [],
                }

            # Aggregate
            template_counts = Counter(i.get("template", "") for i in items)
            user_counts = Counter(i.get("user", "") for i in items)
            daily_counts = Counter(i.get("date", "") for i in items)

            return {
                "period_days": days,
                "total_queries": len(items),
                "unique_users": len(user_counts),
                "top_templates": [
                    {"name": t, "count": c}
                    for t, c in template_counts.most_common(10)
                ],
                "top_users": [
                    {"user": u, "count": c}
                    for u, c in user_counts.most_common(10)
                ],
                "daily_counts": [
                    {"date": d, "count": c}
                    for d, c in sorted(daily_counts.items())
                ],
            }

        except Exception as e:
            logger.error("Failed to get usage summary: %s", e)
            return {"error": str(e)}
