from datetime import datetime, timezone, timedelta
import pytest

from pulse.domain.types import Bank, PaymentMethod, ErrorCode, RouteStatus, PredictiveHealth
from pulse.domain.transaction import Transaction, TransactionResult
from pulse.simulator.scenarios import PaymentScenarioRunner
from pulse.simulator.failures import FailureScenarioType
from pulse.observer.window import SlidingWindow
from pulse.observer.metrics import (
    MetricsCalculator,
    compute_wilson_interval,
    compute_latency_metrics,
)
from pulse.observer.baseline import BaselineManager
from pulse.observer.collector import TelemetryObserver


def make_dummy_result(
    success: bool = True,
    latency_ms: float = 120.0,
    route_id: str = "psp_hdfc_direct",
    bank: Bank = Bank.HDFC,
    error_code: ErrorCode = ErrorCode.NONE,
    timestamp: datetime = None,
) -> TransactionResult:
    txn = Transaction(
        transaction_id="dummy_txn",
        amount_inr=500.0,
        bank=bank,
        payment_method=PaymentMethod.UPI,
        route_id=route_id,
        timestamp=timestamp or datetime.now(timezone.utc),
    )
    return TransactionResult(
        transaction=txn,
        success=success,
        latency_ms=latency_ms,
        error_code=error_code,
    )


class TestSlidingWindow:
    def test_window_retention_and_pruning(self):
        window = SlidingWindow(window_seconds=10)
        base_time = datetime.now(timezone.utc)

        # Add 3 results: 1 old (15s ago), 2 fresh (2s ago)
        old_result = make_dummy_result(timestamp=base_time - timedelta(seconds=15))
        fresh1 = make_dummy_result(timestamp=base_time - timedelta(seconds=2))
        fresh2 = make_dummy_result(timestamp=base_time - timedelta(seconds=1))

        window.add(old_result, timestamp=base_time - timedelta(seconds=15))
        window.add(fresh1, timestamp=base_time - timedelta(seconds=2))
        window.add(fresh2, timestamp=base_time - timedelta(seconds=1))

        window.prune(current_time=base_time)
        results = window.get_results()

        # Old one should be pruned out
        assert len(results) == 2
        assert old_result not in results

    def test_window_clear(self):
        window = SlidingWindow(window_seconds=60)
        window.add(make_dummy_result())
        assert window.count() == 1
        window.clear()
        assert window.count() == 0


class TestMetricsCalculator:
    def test_empty_snapshot(self):
        snap = MetricsCalculator.compute_snapshot([])
        assert snap.total_transactions == 0
        assert snap.success_rate == 1.0
        assert snap.error_rate == 0.0

    def test_exact_rates_and_distributions(self):
        results = [
            make_dummy_result(success=True, latency_ms=100.0),
            make_dummy_result(success=True, latency_ms=120.0),
            make_dummy_result(success=False, latency_ms=4500.0, error_code=ErrorCode.PSP_TIMEOUT),
            make_dummy_result(success=False, latency_ms=80.0, error_code=ErrorCode.AUTH_FAILED),
        ]
        snap = MetricsCalculator.compute_snapshot(results)

        assert snap.total_transactions == 4
        assert snap.successful_transactions == 2
        assert snap.failed_transactions == 2
        assert snap.success_rate == 0.50
        assert snap.error_rate == 0.50
        assert snap.timeout_rate == 0.25
        assert snap.error_distribution[ErrorCode.PSP_TIMEOUT.value] == 1
        assert snap.error_distribution[ErrorCode.AUTH_FAILED.value] == 1

    def test_latency_metrics(self):
        latencies = [100.0, 150.0, 200.0, 250.0, 500.0]
        metrics = compute_latency_metrics(latencies)
        assert metrics.min_ms == 100.0
        assert metrics.max_ms == 500.0
        assert metrics.p50_ms == 200.0
        assert metrics.mean_ms == 240.0

    def test_wilson_confidence_interval(self):
        ci = compute_wilson_interval(successes=95, total=100)
        assert 0.85 < ci.lower < ci.upper <= 1.0

        # Boundary edge case
        ci_zero = compute_wilson_interval(successes=0, total=10)
        assert ci_zero.lower == 0.0
        assert ci_zero.upper > 0.0


class TestBaselineManager:
    def test_default_baselines(self):
        mgr = BaselineManager()
        sys_b = mgr.get_system_baseline()
        assert sys_b.expected_success_rate == 0.985

        hdfc_b = mgr.get_route_baseline("psp_hdfc_direct")
        assert hdfc_b.expected_success_rate == 0.990

    def test_ewma_update_protects_against_degradation(self):
        mgr = BaselineManager(ewma_alpha=0.2)
        initial_sr = mgr.get_system_baseline().expected_success_rate

        # Degraded snapshot must NOT corrupt baseline
        degraded_snap = MetricsCalculator.compute_snapshot([
            make_dummy_result(success=False, error_code=ErrorCode.GATEWAY_ERROR)
            for _ in range(30)
        ])
        mgr.update_with_healthy_snapshot(degraded_snap)
        assert mgr.get_system_baseline().expected_success_rate == initial_sr


class TestTelemetryObserverIntegration:
    def test_observer_with_simulation_scenario(self):
        observer = TelemetryObserver(window_seconds=60)
        runner = PaymentScenarioRunner(seed=42)

        # Ingest 40 healthy transactions
        healthy_results = runner.run_scenario(FailureScenarioType.HEALTHY, count=40)
        observer.record_batch(healthy_results)

        snap = observer.get_snapshot()
        assert snap.total_transactions == 40
        assert snap.success_rate > 0.95
        assert snap.predictive_health == PredictiveHealth.HEALTHY

    def test_quarantine_enforcement(self):
        observer = TelemetryObserver(window_seconds=60)
        observer.record_transaction(make_dummy_result(route_id="psp_failing", success=False))

        observer.quarantine_route("psp_failing", cooldown_seconds=30)
        assert observer.is_route_quarantined("psp_failing") is True

        health = observer.get_route_health("psp_failing")
        assert health is not None
        assert health.status == RouteStatus.QUARANTINED
        assert health.is_quarantined is True

        observer.release_quarantine("psp_failing")
        assert observer.is_route_quarantined("psp_failing") is False
