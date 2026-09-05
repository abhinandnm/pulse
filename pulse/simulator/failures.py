from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import ErrorCode, Bank, PaymentMethod


class FailureScenarioType(str, Enum):
    """Supported deterministic failure injection scenarios."""
    HEALTHY = "HEALTHY"
    PSP_TIMEOUT = "PSP_TIMEOUT"
    BANK_DEGRADATION = "BANK_DEGRADATION"
    AUTH_SPIKE = "AUTH_SPIKE"
    HTTP_500 = "HTTP_500"
    NETWORK_RESET = "NETWORK_RESET"
    TRAFFIC_SURGE = "TRAFFIC_SURGE"
    ROUTE_FLAPPING = "ROUTE_FLAPPING"
    MID_CANARY_FAILURE = "MID_CANARY_FAILURE"
    CASCADING_OUTAGE = "CASCADING_OUTAGE"


class FailureProfile(BaseModel):
    """Configuration for injecting controlled failures in simulation."""
    model_config = ConfigDict(frozen=True)

    scenario_type: FailureScenarioType = FailureScenarioType.HEALTHY
    target_route_id: Optional[str] = None
    target_bank: Optional[Bank] = None
    target_method: Optional[PaymentMethod] = None
    failure_probability: float = Field(default=0.85, ge=0.0, le=1.0)
    latency_min_ms: float = Field(default=80.0, ge=0.0)
    latency_max_ms: float = Field(default=250.0, ge=0.0)
    error_code: ErrorCode = ErrorCode.NONE
    error_message: Optional[str] = None
    traffic_surge_multiplier: float = Field(default=1.0, ge=1.0)
    flapping_cycle_size: int = Field(default=10, ge=2)
    canary_trigger_percentage: int = Field(default=50, ge=1, le=100)


def create_failure_profile(
    scenario_type: FailureScenarioType,
    target_route_id: str = "psp_hdfc_direct",
    target_bank: Optional[Bank] = None,
) -> FailureProfile:
    """Factory helper to build standardized failure profiles for scenarios."""
    if scenario_type == FailureScenarioType.HEALTHY:
        return FailureProfile(
            scenario_type=FailureScenarioType.HEALTHY,
            failure_probability=0.02, # 98% baseline success
            latency_min_ms=80.0,
            latency_max_ms=220.0,
            error_code=ErrorCode.NONE,
        )

    elif scenario_type == FailureScenarioType.PSP_TIMEOUT:
        return FailureProfile(
            scenario_type=FailureScenarioType.PSP_TIMEOUT,
            target_route_id=target_route_id,
            failure_probability=0.85,
            latency_min_ms=3000.0,
            latency_max_ms=5000.0,
            error_code=ErrorCode.PSP_TIMEOUT,
            error_message="Gateway socket timeout after 3000ms",
        )

    elif scenario_type == FailureScenarioType.BANK_DEGRADATION:
        bank = target_bank or Bank.HDFC
        return FailureProfile(
            scenario_type=FailureScenarioType.BANK_DEGRADATION,
            target_bank=bank,
            failure_probability=0.80,
            latency_min_ms=600.0,
            latency_max_ms=1800.0,
            error_code=ErrorCode.ISSUER_DOWN,
            error_message=f"Issuer bank {bank.value} CBS core banking system unreachable",
        )

    elif scenario_type == FailureScenarioType.AUTH_SPIKE:
        return FailureProfile(
            scenario_type=FailureScenarioType.AUTH_SPIKE,
            target_route_id=target_route_id,
            failure_probability=0.70,
            latency_min_ms=400.0,
            latency_max_ms=1200.0,
            error_code=ErrorCode.AUTH_FAILED,
            error_message="OTP delivery timeout / 2FA verification failure",
        )

    elif scenario_type == FailureScenarioType.HTTP_500:
        return FailureProfile(
            scenario_type=FailureScenarioType.HTTP_500,
            target_route_id=target_route_id,
            failure_probability=0.90,
            latency_min_ms=50.0,
            latency_max_ms=300.0,
            error_code=ErrorCode.GATEWAY_ERROR,
            error_message="HTTP 500 Internal Server Error from upstream PSP",
        )

    elif scenario_type == FailureScenarioType.NETWORK_RESET:
        return FailureProfile(
            scenario_type=FailureScenarioType.NETWORK_RESET,
            target_route_id=target_route_id,
            failure_probability=0.75,
            latency_min_ms=10.0,
            latency_max_ms=60.0,
            error_code=ErrorCode.NETWORK_RESET,
            error_message="TCP connection reset by peer during TLS handshake",
        )

    elif scenario_type == FailureScenarioType.TRAFFIC_SURGE:
        return FailureProfile(
            scenario_type=FailureScenarioType.TRAFFIC_SURGE,
            target_route_id=target_route_id,
            failure_probability=0.60,
            latency_min_ms=800.0,
            latency_max_ms=2500.0,
            error_code=ErrorCode.RATE_LIMITED,
            error_message="HTTP 429 Too Many Requests: upstream route concurrency saturated",
            traffic_surge_multiplier=5.0,
        )

    elif scenario_type == FailureScenarioType.ROUTE_FLAPPING:
        return FailureProfile(
            scenario_type=FailureScenarioType.ROUTE_FLAPPING,
            target_route_id=target_route_id,
            failure_probability=0.85,
            latency_min_ms=500.0,
            latency_max_ms=2000.0,
            error_code=ErrorCode.GATEWAY_ERROR,
            error_message="Intermittent route connection failure (flapping)",
            flapping_cycle_size=10,
        )

    elif scenario_type == FailureScenarioType.MID_CANARY_FAILURE:
        return FailureProfile(
            scenario_type=FailureScenarioType.MID_CANARY_FAILURE,
            target_route_id=target_route_id,
            failure_probability=0.90,
            latency_min_ms=2500.0,
            latency_max_ms=4500.0,
            error_code=ErrorCode.PSP_TIMEOUT,
            error_message="Target route failed under load during canary progression",
            canary_trigger_percentage=50,
        )

    elif scenario_type == FailureScenarioType.CASCADING_OUTAGE:
        return FailureProfile(
            scenario_type=FailureScenarioType.CASCADING_OUTAGE,
            target_route_id=target_route_id,
            failure_probability=0.95,
            latency_min_ms=3000.0,
            latency_max_ms=5000.0,
            error_code=ErrorCode.GATEWAY_ERROR,
            error_message="Cascading gateway outage across primary and secondary rails",
        )

    return FailureProfile()
