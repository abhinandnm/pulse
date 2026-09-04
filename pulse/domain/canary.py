import uuid
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import CanaryGateStatus


class CanaryGate(BaseModel):
    """Evaluation result for one of the 5 safety gates during canary testing."""
    model_config = ConfigDict(frozen=True)

    gate_name: str = Field(..., description="Name of gate (e.g. 'MIN_SAMPLE_SIZE', 'LATENCY_SLO')")
    status: CanaryGateStatus = Field(default=CanaryGateStatus.PENDING)
    threshold: float = Field(..., description="Target threshold requirement")
    observed_value: float = Field(..., description="Actual observed measurement")
    passed: bool = Field(default=False)
    message: str = Field(default="", description="Detailed gate check message")


class CanaryConfig(BaseModel):
    """Configuration constraints for canary progressive rollouts."""
    model_config = ConfigDict(frozen=True)

    target_route_id: str
    traffic_stages: List[int] = Field(
        default_factory=lambda: [20, 50, 100],
        description="Sequential canary traffic progression (e.g. 20%, 50%, 100%)"
    )
    min_sample_size: int = Field(default=30, ge=5, description="Minimum transactions needed before gate evaluation")
    min_success_rate: float = Field(default=0.90, ge=0.0, le=1.0, description="Minimum acceptable success rate")
    max_p95_latency_ms: float = Field(default=1500.0, gt=0.0, description="Maximum tolerable p95 latency")
    max_error_rate: float = Field(default=0.05, ge=0.0, le=1.0, description="Maximum allowable error rate")
    evaluation_window_seconds: int = Field(default=30, gt=0, description="Time window for each canary stage")


class CanaryState(BaseModel):
    """Real-time tracking of a canary deployment in progress."""
    model_config = ConfigDict(frozen=True)

    canary_id: str = Field(default_factory=lambda: f"can_{uuid.uuid4().hex[:8]}")
    target_route_id: str
    fallback_route_id: str
    current_traffic_percentage: int = Field(default=20, ge=0, le=100)
    current_stage_index: int = Field(default=0, ge=0)
    status: CanaryGateStatus = Field(default=CanaryGateStatus.PENDING)
    gates: List[CanaryGate] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    promoted: bool = Field(default=False)
    rolled_back: bool = Field(default=False)
