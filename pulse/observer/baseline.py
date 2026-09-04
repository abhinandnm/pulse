from typing import Dict, Optional
from pydantic import BaseModel, Field, ConfigDict
from pulse.domain.types import Bank
from pulse.domain.telemetry import TelemetrySnapshot


class BaselineProfile(BaseModel):
    """Normal operational baseline metrics for comparison during anomalies."""
    model_config = ConfigDict(frozen=True)

    target_id: str
    expected_success_rate: float = Field(default=0.985, ge=0.0, le=1.0)
    expected_p95_latency_ms: float = Field(default=200.0, ge=0.0)
    expected_timeout_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    expected_tpm: float = Field(default=60.0, ge=0.0)


DEFAULT_ROUTE_BASELINES: Dict[str, BaselineProfile] = {
    "psp_hdfc_direct": BaselineProfile(
        target_id="psp_hdfc_direct",
        expected_success_rate=0.990,
        expected_p95_latency_ms=130.0,
        expected_timeout_rate=0.005,
        expected_tpm=120.0,
    ),
    "psp_icici_backup": BaselineProfile(
        target_id="psp_icici_backup",
        expected_success_rate=0.980,
        expected_p95_latency_ms=200.0,
        expected_timeout_rate=0.010,
        expected_tpm=80.0,
    ),
    "psp_aggregator_fallback": BaselineProfile(
        target_id="psp_aggregator_fallback",
        expected_success_rate=0.970,
        expected_p95_latency_ms=260.0,
        expected_timeout_rate=0.015,
        expected_tpm=50.0,
    ),
    # Aliases
    "PSP_A": BaselineProfile(
        target_id="PSP_A",
        expected_success_rate=0.990,
        expected_p95_latency_ms=130.0,
        expected_timeout_rate=0.005,
    ),
    "PSP_B": BaselineProfile(
        target_id="PSP_B",
        expected_success_rate=0.980,
        expected_p95_latency_ms=200.0,
        expected_timeout_rate=0.010,
    ),
    "PSP_C": BaselineProfile(
        target_id="PSP_C",
        expected_success_rate=0.970,
        expected_p95_latency_ms=260.0,
        expected_timeout_rate=0.015,
    ),
}

DEFAULT_BANK_BASELINES: Dict[Bank, float] = {
    Bank.HDFC: 0.990,
    Bank.ICICI: 0.985,
    Bank.SBI: 0.975,
    Bank.AXIS: 0.980,
    Bank.KOTAK: 0.975,
    Bank.OTHER: 0.960,
}


class BaselineManager:
    """Manages baseline metrics and updates via Exponential Weighted Moving Average (EWMA)."""

    def __init__(self, ewma_alpha: float = 0.1):
        self.ewma_alpha = ewma_alpha
        self._route_baselines: Dict[str, BaselineProfile] = dict(DEFAULT_ROUTE_BASELINES)
        self._bank_baselines: Dict[Bank, float] = dict(DEFAULT_BANK_BASELINES)
        self._system_baseline = BaselineProfile(
            target_id="SYSTEM",
            expected_success_rate=0.985,
            expected_p95_latency_ms=200.0,
            expected_timeout_rate=0.010,
            expected_tpm=100.0,
        )

    def get_system_baseline(self) -> BaselineProfile:
        return self._system_baseline

    def get_route_baseline(self, route_id: str) -> BaselineProfile:
        return self._route_baselines.get(
            route_id,
            BaselineProfile(target_id=route_id, expected_success_rate=0.980, expected_p95_latency_ms=220.0),
        )

    def get_bank_baseline_sr(self, bank: Bank) -> float:
        return self._bank_baselines.get(bank, 0.975)

    def update_with_healthy_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        """Gradually adapt baselines only when system is verified healthy."""
        if snapshot.success_rate < 0.95 or snapshot.total_transactions < 20:
            return  # Do not pollute baseline with degraded data

        alpha = self.ewma_alpha
        new_sr = (alpha * snapshot.success_rate) + ((1 - alpha) * self._system_baseline.expected_success_rate)
        new_p95 = (alpha * snapshot.latency.p95_ms) + ((1 - alpha) * self._system_baseline.expected_p95_latency_ms)

        self._system_baseline = BaselineProfile(
            target_id="SYSTEM",
            expected_success_rate=round(new_sr, 4),
            expected_p95_latency_ms=round(new_p95, 2),
            expected_timeout_rate=self._system_baseline.expected_timeout_rate,
        )
