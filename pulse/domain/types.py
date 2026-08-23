from enum import Enum

class SystemState(str,Enum):
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


class RouteStatus(str,Enum):
    """Status of a specific route."""

    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    QUARANTINED = "QUARANTINED"
    STANDBY = "STANDBY"


class Bank(str,Enum):
    """Supported issuer banks"""

    HDFC ="HDFC"
    ICICI = "ICICI"
    SBI = "SBI"
    AXIS = "AXIS"
    KOTAK = "KOTAK"
    OTHER = "OTHER"
class PaymentMethod(str,Enum):
    NET_BANKING = "NET_BANKING"
    UPI = "UPI"
    CARD = "CARD"
    WALLET = "WALLET"


class ErrorCode(str,Enum):

    """failure categories across all payment gateways"""
    NONE = "NONE"
    PSP_TIMEOUT = "PSP_TIMEOUT"
    GATEWAY_ERROR = "GATEWAY_ERROR"
    ISSUER_DOWN = "ISSUER_DOWN"
    AUTH_FAILED = "AUTH_FAILED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    NETWORK_RESET = "NETWORK_RESET"
    RATE_LIMITED = "RATE_LIMITED"

class ActionType(str,Enum):
    """Ccandidate actions evaluated by the Counterfactual Engine"""

    NO_ACTION = "NO_ACTION"
    SWITCH_ROUTE = "SWITCH_ROUTE"
    SPLIT_TRAFFIC_CANARY = "SPLIT_TRAFFIC_CANARY"
    QUARANTINE_ROUTE = "QUARANTINE_ROUTE"
    ROLLBACK = "ROLLBACK"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"

class CanaryGateStatus(str, Enum):
    """Status of canary evaluation gates"""
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





    
    


