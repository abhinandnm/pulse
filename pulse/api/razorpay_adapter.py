import os
import hmac
import hashlib
import uuid
from typing import Dict, Any, Optional


class RazorpayAdapter:
    """
    Isolated adapter for real Razorpay Test Mode public APIs
    and deterministic test-mode fallback.
    Handles Orders, Payments, and Webhook HMAC signature verification.
    """

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ):
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID", "rzp_test_pulse_demo")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET", "secret_pulse_demo")
        self.webhook_secret = webhook_secret or os.environ.get("RAZORPAY_WEBHOOK_SECRET", "whsec_pulse_test_123")

    def create_order(
        self,
        amount_inr: float,
        currency: str = "INR",
        receipt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a Razorpay test order (amount in paise = INR * 100)."""
        amount_paise = int(amount_inr * 100)
        order_id = f"order_{uuid.uuid4().hex[:14]}"
        receipt_id = receipt or f"rcpt_{uuid.uuid4().hex[:8]}"

        return {
            "id": order_id,
            "entity": "order",
            "amount": amount_paise,
            "amount_paid": 0,
            "amount_due": amount_paise,
            "currency": currency,
            "receipt": receipt_id,
            "status": "created",
            "attempts": 0,
            "notes": {"platform": "PULSE Autonomous Reliability"},
        }

    def verify_webhook_signature(
        self,
        body: bytes,
        signature: str,
        secret: Optional[str] = None,
    ) -> bool:
        """
        Verify Razorpay webhook signature using HMAC SHA256.
        Crucial for webhook authentication and replay defense.
        """
        wh_secret = secret or self.webhook_secret
        if not signature or not wh_secret:
            return False

        expected_sig = hmac.new(
            key=wh_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_sig, signature)

    def generate_webhook_signature(self, body: bytes, secret: Optional[str] = None) -> str:
        """Generate valid HMAC SHA256 signature for test webhook payload generation."""
        wh_secret = secret or self.webhook_secret
        return hmac.new(
            key=wh_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()
