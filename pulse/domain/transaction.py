from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import Bank, PaymentMethod, ErrorCode


class Transaction(BaseModel):
    """Represents an incoming payment transaction attempt."""
    model_config = ConfigDict(frozen=True)

    transaction_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    amount_inr: float = Field(gt=0, description="Transaction amount in INR (must be > 0)")
    bank: Bank
    payment_method: PaymentMethod
    route_id: str
    merchant_id: str = "merchant_default"
    customer_id: Optional[str] = None


class TransactionResult(BaseModel):
    """The execution result of a transaction through a payment gateway."""
    model_config = ConfigDict(frozen=True)

    transaction: Transaction
    success: bool
    latency_ms: float = Field(ge=0.0, description="Gateway response latency in milliseconds")
    error_code: ErrorCode = ErrorCode.NONE
    error_message: Optional[str] = None
    psp_reference: Optional[str] = None
