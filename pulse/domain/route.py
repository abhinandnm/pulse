from datetime import datetime,timezone
from typing import List, Optional
from pydantic import BaseModel,Field,ConfigDict

from pulse.domain.types import RouteStatus,Bank,PaymentMethod


class PaymentRoute(BaseModel):
     """Static configuration and capabilities of a payment gateway route."""
     model_config = ConfigDict(frozen=True)
     route_id: str = Field(..., description="Unique route identifier (e.g. 'psp_hdfc_direct')")
     name: str = Field(..., description="Human-readable route name")

     supported_methods:List[PaymentMethod]=Field(default_factory=list)
     supported_banks: List[Bank] = Field(default_factory=list)
     cost_per_txn_inr: float = Field(default=0.0, ge=0.0, description="Base processing fee per transaction")


class RouteHealth(BaseModel):
    """Real-time health and performance metrics for a route."""
    model_config = ConfigDict(frozen=True)

    route_id: str = Field(..., description="Target route identifier")
    status: RouteStatus = Field(default=RouteStatus.ACTIVE, description="Current operational status")
    success_rate: float = Field(default=1.0, ge=0.0, le=1.0, description="Rolling success rate (0.0 to 1.0)")
    p95_latency_ms: float = Field(default=0.0, ge=0.0, description="95th percentile latency in milliseconds")
    is_quarantined: bool = Field(default=False, description="Whether route is temporarily blocked from traffic")
    quarantined_until: Optional[datetime] = Field(default=None, description="Cooldown expiration timestamp if quarantined")
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp of last health evaluation")
