import uuid
from datetime import datetime, timezone
from typing import List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import IncidentSeverity, ActionType


class DiagnosticEvidence(BaseModel):
    """Factual telemetry observation supporting an incident diagnosis."""
    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(default_factory=lambda: f"evi_{uuid.uuid4().hex[:8]}")
    metric_name: str = Field(..., description="Name of the metric observed (e.g. 'timeout_rate')")
    observed_value: Union[float, str] = Field(..., description="Value observed during degradation")
    threshold_value: Union[float, str] = Field(..., description="Expected baseline or threshold limit")
    description: str = Field(..., description="Human-readable explanation of the anomaly")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DiagnosticHypothesis(BaseModel):
    """Hypothesis formed by the AI Doctor or rule engine explaining root cause."""
    model_config = ConfigDict(frozen=True)

    hypothesis_id: str = Field(default_factory=lambda: f"hyp_{uuid.uuid4().hex[:8]}")
    title: str = Field(..., description="Short title of the hypothesis")
    description: str = Field(..., description="Detailed explanation of the suspected cause")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in this hypothesis (0.0 to 1.0)")
    supporting_evidence: List[DiagnosticEvidence] = Field(default_factory=list)
    recommended_action: ActionType = Field(..., description="Action suggested to remediate this issue")
    target_route_id: Optional[str] = Field(default=None, description="Target route to reroute to or quarantine")


class IncidentRecord(BaseModel):
    """Full historical and operational record of an incident."""
    model_config = ConfigDict(frozen=True)

    incident_id: str = Field(default_factory=lambda: f"inc_{uuid.uuid4().hex[:8]}")
    severity: IncidentSeverity = Field(default=IncidentSeverity.MEDIUM)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    trigger_metric: str = Field(..., description="Metric that breached threshold (e.g. 'success_rate < 0.85')")
    root_cause: str = Field(default="UNKNOWN", description="Diagnosed root cause")
    hypotheses: List[DiagnosticHypothesis] = Field(default_factory=list)
    actions_taken: List[ActionType] = Field(default_factory=list)
    revenue_at_risk_inr: float = Field(default=0.0, ge=0.0, description="Financial volume exposed during incident")
    recovered_revenue_inr: float = Field(default=0.0, ge=0.0, description="Prevented revenue loss after recovery")
    is_resolved: bool = Field(default=False)
