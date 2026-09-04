import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Union
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import SystemState, ActionType


class StateTransitionEvent(BaseModel):
    """Emitted whenever the Pulse FSM changes system state."""
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:8]}")
    from_state: SystemState
    to_state: SystemState
    reason: str = Field(..., description="Explanation of why transition occurred")
    trigger: str = Field(default="AUTOMATIC", description="Triggering event or component")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    """Immutable audit trail for compliance, post-mortems, and dashboard feeds."""
    model_config = ConfigDict(frozen=True)

    audit_id: str = Field(default_factory=lambda: f"aud_{uuid.uuid4().hex[:8]}")
    actor: str = Field(..., description="Entity performing action ('AI_DOCTOR', 'SAFETY_CONTROLLER', 'HUMAN')")
    action: Union[ActionType, str] = Field(..., description="Action attempted or executed")
    description: str = Field(..., description="Human-readable description of what took place")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = Field(default_factory=dict)
