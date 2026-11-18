"""
Cost Estimator

Estimates AWS service costs per pipeline execution based on
actual resource consumption. Helps teams understand the true
cost of their data pipelines.

Pricing reference (us-east-1, as of 2024):
  - Glue ETL: $0.44 per DPU-hour
  - Athena:   $5.00 per TB scanned
  - S3:       $0.005 per 1,000 PUT requests
  - Lambda:   $0.0000166667 per GB-second
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PricingConfig:
    """AWS pricing per unit (us-east-1 defaults)."""

    glue_dpu_hour: float = 0.44
    athena_per_tb: float = 5.00
    s3_put_per_1k: float = 0.005
    s3_get_per_1k: float = 0.0004
    s3_storage_gb_month: float = 0.023
    lambda_gb_second: float = 0.0000166667
    lambda_request: float = 0.0000002
    dynamodb_wcu: float = 0.00065  # per WCU-hour
    dynamodb_rcu: float = 0.00013  # per RCU-hour
    sns_per_request: float = 0.0000005


class CostEstimator:
    """Estimate AWS costs for pipeline operations."""

    def __init__(self, pricing: Optional[PricingConfig] = None):
        self.pricing = pricing or PricingConfig()

    def estimate_glue(
        self,
        dpu_seconds: float,
        max_capacity: float = 2,
    ) -> float:
        """
        Estimate Glue ETL job cost.

        Args:
            dpu_seconds: Execution time in seconds (from Glue event).
            max_capacity: Max DPU capacity allocated.

        Returns:
            Estimated cost in USD.
        """
        # Glue bills per DPU-hour with 1-minute minimum, rounded up
        dpu_hours = max(dpu_seconds, 60) / 3600
        cost = dpu_hours * max_capacity * self.pricing.glue_dpu_hour
        return round(cost, 6)

    def estimate_athena(self, bytes_scanned: int) -> float:
        """
        Estimate Athena query cost.

        Args:
            bytes_scanned: Bytes scanned by the query.

        Returns:
            Estimated cost in USD.
        """
        # Athena has a 10 MB minimum charge per query
        min_bytes = 10 * 1024 * 1024
        effective_bytes = max(bytes_scanned, min_bytes)
        tb = effective_bytes / (1024 ** 4)
        cost = tb * self.pricing.athena_per_tb
        return round(cost, 6)

    def estimate_lambda(
        self,
        duration_ms: float,
        memory_mb: int = 128,
        invocations: int = 1,
    ) -> float:
        """
        Estimate Lambda execution cost.

        Args:
            duration_ms: Execution duration in milliseconds.
            memory_mb: Memory allocated in MB.
            invocations: Number of invocations.

        Returns:
            Estimated cost in USD.
        """
        # Lambda bills per 1ms with minimum 1ms
        gb_seconds = (max(duration_ms, 1) / 1000) * (memory_mb / 1024)
        compute_cost = gb_seconds * self.pricing.lambda_gb_second * invocations
        request_cost = invocations * self.pricing.lambda_request
        return round(compute_cost + request_cost, 8)

    def estimate_s3_operations(
        self,
        put_requests: int = 0,
        get_requests: int = 0,
        storage_gb: float = 0,
    ) -> float:
        """Estimate S3 cost for operations and storage."""
        put_cost = (put_requests / 1000) * self.pricing.s3_put_per_1k
        get_cost = (get_requests / 1000) * self.pricing.s3_get_per_1k
        storage_cost = storage_gb * self.pricing.s3_storage_gb_month
        return round(put_cost + get_cost + storage_cost, 6)

    def estimate_pipeline_run(
        self,
        glue_dpu_seconds: float = 0,
        glue_max_capacity: float = 2,
        athena_bytes_scanned: int = 0,
        lambda_duration_ms: float = 0,
        lambda_memory_mb: int = 128,
        lambda_invocations: int = 0,
        s3_put_requests: int = 0,
        s3_get_requests: int = 0,
    ) -> dict:
        """
        Estimate total cost of a pipeline run across all services.

        Returns:
            Breakdown with per-service and total cost.
        """
        breakdown = {}

        if glue_dpu_seconds > 0:
            breakdown["glue"] = self.estimate_glue(
                glue_dpu_seconds, glue_max_capacity,
            )

        if athena_bytes_scanned > 0:
            breakdown["athena"] = self.estimate_athena(athena_bytes_scanned)

        if lambda_invocations > 0:
            breakdown["lambda"] = self.estimate_lambda(
                lambda_duration_ms, lambda_memory_mb, lambda_invocations,
            )

        if s3_put_requests > 0 or s3_get_requests > 0:
            breakdown["s3"] = self.estimate_s3_operations(
                s3_put_requests, s3_get_requests,
            )

        breakdown["total"] = round(sum(breakdown.values()), 6)

        return breakdown
