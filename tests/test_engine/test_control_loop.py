import pytest
from pulse.domain.types import (
    OperatingMode,
    SystemState,
    ActionType,
    CanaryGateStatus,
    Bank,
    PaymentMethod,
    ErrorCode,
)
from pulse.domain.transaction import Transaction, TransactionResult
from pulse.observer.collector import TelemetryObserver
from pulse.simulator.scenarios import PaymentScenarioRunner
from pulse.simulator.failures import FailureScenarioType
from pulse.memory.repository import IncidentRepository
from pulse.engine.loop import AutonomousControlLoop, PulseLoopResult


def make_canary_results(count: int, success: bool = True, latency_ms: float = 120.0) -> list:
    res = []
    for i in range(count):
        txn = Transaction(
            transaction_id=f"canary_txn_{i}",
            amount_inr=1000.0,
            bank=Bank.HDFC,
            payment_method=PaymentMethod.UPI,
            route_id="psp_icici_backup",
        )
        res.append(
            TransactionResult(
                transaction=txn,
                success=success,
                latency_ms=latency_ms,
                error_code=ErrorCode.NONE if success else ErrorCode.GATEWAY_ERROR,
            )
        )
    return res


class TestAutonomousControlLoop:
    def setup_method(self):
        self.observer = TelemetryObserver(window_seconds=60)
        self.repo = IncidentRepository()

    def test_observe_mode_does_not_actuate(self):
        loop = AutonomousControlLoop(
            observer=self.observer,
            operating_mode=OperatingMode.OBSERVE,
            repository=self.repo,
        )
        runner = PaymentScenarioRunner(seed=42)

        # Ingest degraded scenario
        bad_results = runner.run_scenario(
            FailureScenarioType.PSP_TIMEOUT,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        self.observer.record_batch(bad_results)

        result = loop.step()
        assert result.anomaly_detected is True
        assert result.diagnosis is not None
        assert result.exposure_report is not None
        assert result.action_executed is False
        assert loop.fsm.current_state == SystemState.EVALUATING

    def test_assisted_mode_prepares_pending_decision(self):
        loop = AutonomousControlLoop(
            observer=self.observer,
            operating_mode=OperatingMode.ASSISTED,
            repository=self.repo,
        )
        runner = PaymentScenarioRunner(seed=42)

        bad_results = runner.run_scenario(
            FailureScenarioType.PSP_TIMEOUT,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        self.observer.record_batch(bad_results)

        result = loop.step()
        assert result.anomaly_detected is True
        assert result.action_executed is False
        assert loop.pending_assisted_decision is not None

    def test_autonomous_mode_initiates_canary(self):
        loop = AutonomousControlLoop(
            observer=self.observer,
            operating_mode=OperatingMode.AUTONOMOUS,
            repository=self.repo,
        )
        runner = PaymentScenarioRunner(seed=42)

        bad_results = runner.run_scenario(
            FailureScenarioType.PSP_TIMEOUT,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        self.observer.record_batch(bad_results)

        # Step 1: Detects, diagnoses, and starts CANARY
        res1 = loop.step()
        assert res1.anomaly_detected is True
        assert res1.action_executed is True
        assert loop.fsm.current_state == SystemState.CANARY
        assert loop.active_canary_state is not None
        assert loop.active_canary_state.current_traffic_percentage == 20

    def test_full_autonomous_canary_promotion_lifecycle(self):
        loop = AutonomousControlLoop(
            observer=self.observer,
            operating_mode=OperatingMode.AUTONOMOUS,
            repository=self.repo,
        )
        runner = PaymentScenarioRunner(seed=42)

        # Trigger anomaly
        bad_results = runner.run_scenario(
            FailureScenarioType.PSP_TIMEOUT,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        self.observer.record_batch(bad_results)
        loop.step()
        assert loop.fsm.current_state == SystemState.CANARY

        # Canary Stage 0 (20%) -> provide 30 healthy candidate txns
        step2 = loop.step(candidate_canary_results=make_canary_results(30, success=True))
        assert loop.active_canary_state.current_traffic_percentage == 50

        # Canary Stage 1 (50%) -> provide 30 healthy candidate txns
        step3 = loop.step(candidate_canary_results=make_canary_results(30, success=True))
        assert loop.active_canary_state.current_traffic_percentage == 100

        # Canary Stage 2 (100%) -> provide 30 healthy candidate txns -> PROMOTION!
        step4 = loop.step(candidate_canary_results=make_canary_results(30, success=True))
        assert loop.fsm.current_state == SystemState.HEALTHY
        assert loop.active_canary_state is None

        # Verify incident was closed in repository and revenue recovered was logged
        incidents = self.repo.list_incidents()
        assert len(incidents) > 0
        assert incidents[0].is_resolved is True
        assert incidents[0].recovered_revenue_inr > 0.0

    def test_autonomous_canary_rollback_lifecycle(self):
        loop = AutonomousControlLoop(
            observer=self.observer,
            operating_mode=OperatingMode.AUTONOMOUS,
            repository=self.repo,
        )
        runner = PaymentScenarioRunner(seed=42)

        # Trigger anomaly
        bad_results = runner.run_scenario(
            FailureScenarioType.PSP_TIMEOUT,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        self.observer.record_batch(bad_results)
        loop.step()
        assert loop.fsm.current_state == SystemState.CANARY

        # Canary fails due to errors on candidate route!
        failing_results = make_canary_results(30, success=False, latency_ms=4500.0)
        step_rollback = loop.step(candidate_canary_results=failing_results)

        # FSM must transition through ROLLED_BACK to QUARANTINED
        assert loop.fsm.current_state == SystemState.QUARANTINED
        assert loop.active_canary_state is None
        assert step_rollback.chosen_action == ActionType.ROLLBACK
