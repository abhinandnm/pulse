from enum import Enum

class SystemState(str, Enum):
    """The strict Finite State Machine (FSM) states for Pulse."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DIAGNOSING = "DIAGNOSING"
    EVALUATING = "EVALUATING"
    CANARY = "CANARY"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"
    QUARANTINED = "QUARANTINED"
    ESCALATED = "ESCALATED"


class RouteStatus(str, Enum):
    """Status of a specific route."""
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    QUARANTINED = "QUARANTINED"
    STANDBY = "STANDBY"


class Bank(str, Enum):
    """Supported issuer banks."""
    HDFC = "HDFC"
    ICICI = "ICICI"
    SBI = "SBI"
    AXIS = "AXIS"
    KOTAK = "KOTAK"
    OTHER = "OTHER"


class PaymentMethod(str, Enum):
    """Supported payment methods."""
    NET_BANKING = "NET_BANKING"
    UPI = "UPI"
    CARD = "CARD"
    WALLET = "WALLET"


class ErrorCode(str, Enum):
    """Failure categories across all payment gateways."""
    NONE = "NONE"
    PSP_TIMEOUT = "PSP_TIMEOUT"
    GATEWAY_ERROR = "GATEWAY_ERROR"
    ISSUER_DOWN = "ISSUER_DOWN"
    AUTH_FAILED = "AUTH_FAILED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    NETWORK_RESET = "NETWORK_RESET"
    RATE_LIMITED = "RATE_LIMITED"


class ActionType(str, Enum):
    """Candidate actions evaluated by the Counterfactual Engine."""
    NO_ACTION = "NO_ACTION"
    SWITCH_ROUTE = "SWITCH_ROUTE"
    SPLIT_TRAFFIC_CANARY = "SPLIT_TRAFFIC_CANARY"
    QUARANTINE_ROUTE = "QUARANTINE_ROUTE"
    ROLLBACK = "ROLLBACK"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"


class CanaryGateStatus(str, Enum):
    """Status of canary evaluation gates."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    SKIPPED = "SKIPPED"


class IncidentSeverity(str, Enum):
    """Severity classification for anomalies."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PaymentState(str, Enum):
    """Explicit lifecycle states of a payment."""
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class OperatingMode(str, Enum):
    """Automation level of the Pulse engine."""
    OBSERVE = "OBSERVE"          # Monitor only, log recommendations
    ASSISTED = "ASSISTED"        # Recommend actions, require human approval
    AUTONOMOUS = "AUTONOMOUS"    # Execute safe actions (canary/rollback) autonomously


class PredictiveHealth(str, Enum):
    """Statistical trend indicator for route & system health."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class WebhookEventType(str, Enum):
    """Razorpay test webhook events."""
    PAYMENT_AUTHORIZED = "payment.authorized"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_CAPTURED = "payment.captured"
    ORDER_PAID = "order.paid"
    REFUND_PROCESSED = "refund.processed"
