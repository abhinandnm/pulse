import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator

from pulse.domain.types import Bank, PaymentMethod, ErrorCode, PaymentState


class Transaction(BaseModel):
    """Represents an incoming payment transaction attempt."""
    model_config = ConfigDict(frozen=True)

    transaction_id: str
    idempotency_key: str = Field(
        default_factory=lambda: f"idemp_{uuid.uuid4().hex[:12]}",
        description="Unique key to prevent duplicate charges on retry"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    amount_inr: float = Field(gt=0, description="Transaction amount in INR (must be > 0)")
    bank: Bank
    payment_method: PaymentMethod
    route_id: str
    merchant_id: str = "merchant_default"
    customer_id: Optional[str] = None
    payment_state: PaymentState = PaymentState.CREATED
    retry_count: int = Field(default=0, ge=0, description="Number of times this transaction has been retried")
    is_synthetic: bool = Field(default=False, description="True if generated for canary or probe health checks")


class TransactionResult(BaseModel):
    """The execution result of a transaction through a payment gateway."""
    model_config = ConfigDict(frozen=True)

    transaction: Transaction
    success: bool
    latency_ms: float = Field(ge=0.0, description="Gateway response latency in milliseconds")
    error_code: ErrorCode = ErrorCode.NONE
    error_message: Optional[str] = None
    psp_reference: Optional[str] = None
    payment_state: PaymentState = PaymentState.CAPTURED

    @model_validator(mode="before")
    @classmethod
    def set_default_payment_state(cls, data):
        # 1. Bro, pydantic dumps all incoming raw arguments into this 'data' dictionary before building the object.
        # If nobody told us what the payment_state is, we gotta figure it out ourselves:
        if isinstance(data, dict) and "payment_state" not in data:
            # 2. Pull the 2 main clues: did it pass (success)? what went wrong (error_code)?
            success = data.get("success", False)
            error_code = data.get("error_code", ErrorCode.NONE)

            # 3. Time to decide: is it a win, a mystery timeout, or a clean fail?
            if success:
                # Paisa settled in bank safely -> CAPTURED!
                data["payment_state"] = PaymentState.CAPTURED
            elif error_code == ErrorCode.PSP_TIMEOUT:
                # Gateway went ghost! Don't retry blindly or customer gets debited twice -> UNKNOWN!
                data["payment_state"] = PaymentState.UNKNOWN
            else:
                # Clean rejection (bad pin, no balance, bank down) -> FAILED!
                data["payment_state"] = PaymentState.FAILED

        # 4. Hand back the modified dict so pydantic can lock it in as a frozen object.
        return data
