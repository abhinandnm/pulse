import uuid
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import ActionType


class CandidateEvaluation(BaseModel):
    """Evaluation of a specific recovery candidate action."""
    model_config = ConfigDict(frozen=True)

    action: ActionType
    target_route_id: Optional[str] = None
    expected_sr_lift: float = Field(description="Expected change in success rate (e.g. +0.20)")
    estimated_cost_delta_inr: float = Field(default=0.0, description="Cost change per transaction in INR")
    risk_score: float = Field(ge=0.0, le=1.0, description="Risk of route saturation or failure (0.0 to 1.0)")
    utility_score: float = Field(description="Composite utility score balancing recovery vs risk")
    rationale: str = Field(..., description="Explanation of evaluation rationale")


class CounterfactualDecision(BaseModel):
    """Decision output by the Counterfactual Engine comparing candidate actions."""
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:8]}")
    incident_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evaluated_candidates: List[CandidateEvaluation] = Field(default_factory=list)
    chosen_action: ActionType
    chosen_route_id: Optional[str] = None
    projected_revenue_recovery_inr: float = Field(default=0.0, ge=0.0)
    explanation: str
