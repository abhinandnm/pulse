import pytest
from pulse.domain.telemetry import TelemetrySnapshot
from pulse.accountant.engine import RevenueAccountant, FinancialExposureReport
from pulse.observer.baseline import BaselineManager, BaselineProfile


class TestRevenueAccountant:
    def setup_method(self):
        self.accountant = RevenueAccountant()

    def test_zero_exposure_when_healthy(self):
        snap = TelemetrySnapshot(
            window_seconds=60,
            total_transactions=100,
            successful_transactions=99,
            failed_transactions=1,
            success_rate=0.99,  # Above 98.5% baseline
        )
        report = self.accountant.calculate_exposure(snap, default_aov=1000.0)
        assert report.current_exposure_inr == 0.0
        assert report.projected_1h_exposure_inr == 0.0
        assert report.projected_24h_exposure_inr == 0.0
        assert report.is_estimated is True

    def test_exact_exposure_calculation(self):
        # 100 txns in 60s, baseline 0.985, current 0.685 -> delta is exactly 0.30
        snap = TelemetrySnapshot(
            window_seconds=60,
            total_transactions=100,
            successful_transactions=68,
            failed_transactions=32,
            success_rate=0.685,
        )
        report = self.accountant.calculate_exposure(snap, default_aov=1000.0)

        # 0.30 * 100 txns * 1000 INR = 30,000 INR
        assert report.current_exposure_inr == 30000.0

        # TPM = 100. 1 Hour = 6000 txns. 6000 * 0.30 * 1000 = 1,800,000 INR
        assert report.projected_1h_exposure_inr == 1800000.0

        # 24 Hours = 1,800,000 * 24 = 43,200,000 INR
        assert report.projected_24h_exposure_inr == 43200000.0
        assert report.is_estimated is True

    def test_prevented_loss_post_recovery(self):
        # Degraded was 70%, recovered to 98% across 500 txns with AOV 1500 INR
        prevented = self.accountant.calculate_prevented_loss(
            degraded_sr=0.70,
            recovered_sr=0.98,
            post_recovery_volume=500,
            aov=1500.0,
        )
        # Delta: 0.28 * 500 * 1500 = 210,000 INR
        assert prevented == 210000.0

    def test_negative_lift_yields_zero_prevented(self):
        prevented = self.accountant.calculate_prevented_loss(
            degraded_sr=0.80,
            recovered_sr=0.75,  # Worse than degraded
            post_recovery_volume=100,
            aov=1000.0,
        )
        assert prevented == 0.0
