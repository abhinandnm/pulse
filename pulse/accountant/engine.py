from datetime import datetime, timezone
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.telemetry import TelemetrySnapshot
from pulse.domain.transaction import TransactionResult
from pulse.observer.baseline import BaselineManager, BaselineProfile


class FinancialExposureReport(BaseModel):
    """
    Quantified financial impact and revenue exposure.
    All figures are explicitly marked as ESTIMATED based on baseline telemetry.
    """
    model_config = ConfigDict(frozen=True)

    current_exposure_inr: float = Field(ge=0.0, description="Estimated revenue lost in the current active window (INR)")
    projected_1h_exposure_inr: float = Field(ge=0.0, description="Estimated projected exposure over 1 hour if unresolved (INR)")
    projected_24h_exposure_inr: float = Field(ge=0.0, description="Estimated projected exposure over 24 hours if unresolved (INR)")
    prevented_exposure_inr: float = Field(default=0.0, ge=0.0, description="Estimated revenue loss prevented post-recovery (INR)")
    aov_inr: float = Field(ge=0.0, description="Average Order Value in INR")
    baseline_sr: float = Field(ge=0.0, le=1.0, description="Expected baseline success rate")
    current_sr: float = Field(ge=0.0, le=1.0, description="Observed degraded success rate")
    volume_per_minute: float = Field(ge=0.0, description="Observed transaction rate (TPM)")
    currency: str = "INR"
    is_estimated: bool = True
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RevenueAccountant:
    """
    Calculates revenue-at-risk and financial exposure resulting from payment degradation.
    Formula:
        Revenue At Risk = max(0, Baseline_SR - Current_SR) * Volume * AOV
    """

    def __init__(self, baseline_manager: Optional[BaselineManager] = None):
        self.baseline_manager = baseline_manager or BaselineManager()

    def calculate_exposure(
        self,
        snapshot: TelemetrySnapshot,
        results: Optional[List[TransactionResult]] = None,
        default_aov: float = 1200.0,
    ) -> FinancialExposureReport:
        """Calculate current and projected revenue-at-risk from telemetry."""
        system_baseline = self.baseline_manager.get_system_baseline()
        baseline_sr = system_baseline.expected_success_rate
        current_sr = snapshot.success_rate

        # Calculate actual Average Order Value (AOV) from results if provided
        if results and len(results) > 0:
            aov = sum(r.transaction.amount_inr for r in results) / len(results)
        else:
            aov = default_aov

        sr_delta = max(0.0, baseline_sr - current_sr)

        # Transactions per minute (TPM) based on window duration
        window_sec = max(1, snapshot.window_seconds)
        tpm = (snapshot.total_transactions / window_sec) * 60.0

        # Current window exposure
        current_lost_txns = sr_delta * snapshot.total_transactions
        current_exposure = round(current_lost_txns * aov, 2)

        # 1-Hour projection: TPM * 60 minutes * SR Delta * AOV
        hourly_txns = tpm * 60.0
        projected_1h = round(hourly_txns * sr_delta * aov, 2)

        # 24-Hour projection
        projected_24h = round(projected_1h * 24.0, 2)

        return FinancialExposureReport(
            current_exposure_inr=current_exposure,
            projected_1h_exposure_inr=projected_1h,
            projected_24h_exposure_inr=projected_24h,
            prevented_exposure_inr=0.0,
            aov_inr=round(aov, 2),
            baseline_sr=baseline_sr,
            current_sr=current_sr,
            volume_per_minute=round(tpm, 2),
            is_estimated=True,
        )

    def calculate_prevented_loss(
        self,
        degraded_sr: float,
        recovered_sr: float,
        post_recovery_volume: int,
        aov: float = 1200.0,
    ) -> float:
        """
        Quantify estimated exposure prevented post-recovery.
        Formula: max(0, Recovered_SR - Degraded_SR) * Volume * AOV
        """
        sr_lift = max(0.0, recovered_sr - degraded_sr)
        prevented = round(sr_lift * post_recovery_volume * aov, 2)
        return prevented
