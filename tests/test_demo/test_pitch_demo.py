"""End-to-End Demo Pitch Test."""

import pytest
from pulse.domain.types import (
    OperatingMode,
    SystemState,
    ActionType,
    Bank,
    PaymentMethod,
)
from pulse.domain.transaction import Transaction, TransactionResult
from pulse.observer.collector import TelemetryObserver
from pulse.memory.repository import IncidentRepository
from pulse.simulator.scenarios import PaymentScenarioRunner
from pulse.simulator.failures import FailureScenarioType
from pulse.engine.loop import AutonomousControlLoop


def test_full_pitch_demo_lifecycle():
    """Verify that the end-to-end demo pitch workflow runs autonomously from detection to recovery."""
    observer = TelemetryObserver(window_seconds=60)
    repo = IncidentRepository()
    loop = AutonomousControlLoop(observer=observer, operating_mode=OperatingMode.AUTONOMOUS, repository=repo)

    # 1. Baseline
    runner = PaymentScenarioRunner(seed=101)
    healthy_batch = runner.run_scenario(FailureScenarioType.HEALTHY, count=50)
    observer.record_batch(healthy_batch)
    loop.step()
    assert loop.fsm.current_state == SystemState.HEALTHY

    # 2. Inject Anomaly
    failure_batch = runner.run_scenario(
        FailureScenarioType.PSP_TIMEOUT,
        count=40,
        target_route_id="psp_hdfc_direct",
    )
    observer.record_batch(failure_batch)

    # 3. Detection & Canary Initiation
    res_anomaly = loop.step()
    assert res_anomaly.anomaly_detected is True
    assert loop.fsm.current_state == SystemState.CANARY
    assert res_anomaly.diagnosis is not None
    assert res_anomaly.exposure_report is not None

    # 4. Progressive Canary Progression: Stage 0 (20%) -> Stage 1 (50%) -> Stage 2 (100%)
    make_txns = lambda stage: [
        TransactionResult(
            transaction=Transaction(
                transaction_id=f"canary_{stage}_{i}",
                amount_inr=1500.0,
                bank=Bank.HDFC,
                payment_method=PaymentMethod.UPI,
                route_id="psp_icici_backup",
            ),
            success=True,
            latency_ms=100.0,
        )
        for i in range(25)
    ]

    loop.step(candidate_canary_results=make_txns(0))
    assert loop.active_canary_state.current_traffic_percentage == 50

    loop.step(candidate_canary_results=make_txns(1))
    assert loop.active_canary_state.current_traffic_percentage == 100

    res_promoted = loop.step(candidate_canary_results=make_txns(2))
    assert loop.fsm.current_state == SystemState.HEALTHY
    assert loop.active_canary_state is None

    # 5. Incident Verification
    incidents = repo.list_incidents()
    assert len(incidents) > 0
    assert incidents[0].is_resolved is True
    assert incidents[0].recovered_revenue_inr > 0
