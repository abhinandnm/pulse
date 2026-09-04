import uuid
from datetime import datetime, timezone
from typing import Dict, Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import ErrorCode, Bank, PredictiveHealth
from pulse.domain.route import RouteHealth


class ConfidenceInterval(BaseModel):
    """Wilson Score confidence interval for statistical rates."""
    model_config = ConfigDict(frozen=True)

    lower: float = Field(ge=0.0, le=1.0, description="Lower bound of confidence interval")
    upper: float = Field(ge=0.0, le=1.0, description="Upper bound of confidence interval")
    confidence_level: float = Field(default=0.95, ge=0.0, le=1.0, description="Confidence level (e.g. 0.95 for 95%)")


class LatencyMetrics(BaseModel):
    """Latency distribution percentiles in milliseconds."""
    model_config = ConfigDict(frozen=True)

    p50_ms: float = Field(ge=0.0, default=0.0)
    p90_ms: float = Field(ge=0.0, default=0.0)
    p95_ms: float = Field(ge=0.0, default=0.0)
    p99_ms: float = Field(ge=0.0, default=0.0)
    mean_ms: float = Field(ge=0.0, default=0.0)
    min_ms: float = Field(ge=0.0, default=0.0)
    max_ms: float = Field(ge=0.0, default=0.0)


class TelemetrySnapshot(BaseModel):
    """Aggregated operational metrics for a specific time window."""
    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    window_seconds: int = Field(default=60, gt=0)
    total_transactions: int = Field(default=0, ge=0)
    successful_transactions: int = Field(default=0, ge=0)
    failed_transactions: int = Field(default=0, ge=0)
    success_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    timeout_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    latency: LatencyMetrics = Field(default_factory=LatencyMetrics)
    success_rate_ci: Optional[ConfidenceInterval] = None
    route_health: Dict[str, RouteHealth] = Field(default_factory=dict)
    error_distribution: Dict[str, int] = Field(default_factory=dict)
    bank_breakdown: Dict[str, float] = Field(default_factory=dict)
    predictive_health: PredictiveHealth = PredictiveHealth.HEALTHY
