import pytest
from pulse.domain.types import SystemState
from pulse.domain.events import StateTransitionEvent
from pulse.fsm.machine import PulseStateMachine, InvalidStateTransitionError


class TestPulseStateMachine:
    def test_initial_state_and_success_flow(self):
        events = []
        fsm = PulseStateMachine(
            initial_state=SystemState.HEALTHY,
            on_transition=lambda e: events.append(e),
        )
        assert fsm.current_state == SystemState.HEALTHY

        # 1. Anomaly detected
        e1 = fsm.transition_to(SystemState.DEGRADED, reason="Success rate dropped below 85%")
        assert fsm.current_state == SystemState.DEGRADED
        assert e1.from_state == SystemState.HEALTHY
        assert e1.to_state == SystemState.DEGRADED

        # 2. AI Doctor begins diagnosis
        fsm.transition_to(SystemState.DIAGNOSING, reason="AI Doctor analyzing root cause evidence")
        assert fsm.current_state == SystemState.DIAGNOSING

        # 3. Counterfactual engine evaluating options
        fsm.transition_to(SystemState.EVALUATING, reason="Ranking candidate recovery routes")
        assert fsm.current_state == SystemState.EVALUATING

        # 4. Initiate progressive canary
        fsm.transition_to(SystemState.CANARY, reason="Canary split started on psp_icici_backup")
        assert fsm.current_state == SystemState.CANARY

        # 5. All 5 gates pass -> Promoted
        fsm.transition_to(SystemState.PROMOTED, reason="Canary passed all 5 gates successfully")
        assert fsm.current_state == SystemState.PROMOTED

        # 6. Restored to healthy
        fsm.transition_to(SystemState.HEALTHY, reason="Operational metrics verified stable")
        assert fsm.current_state == SystemState.HEALTHY

        # Verify history & callback events
        assert len(fsm.history) == 6
        assert len(events) == 6

    def test_rollback_and_quarantine_flow(self):
        fsm = PulseStateMachine(initial_state=SystemState.HEALTHY)
        fsm.transition_to(SystemState.DEGRADED, reason="Timeout spike")
        fsm.transition_to(SystemState.DIAGNOSING, reason="Diagnosing")
        fsm.transition_to(SystemState.EVALUATING, reason="Evaluating")
        fsm.transition_to(SystemState.CANARY, reason="Canary started")

        # Gate fails -> Rollback
        fsm.transition_to(SystemState.ROLLED_BACK, reason="Canary gate LATENCY_SLO breached")
        assert fsm.current_state == SystemState.ROLLED_BACK

        # Automated quarantine
        fsm.transition_to(SystemState.QUARANTINED, reason="Quarantining candidate route")
        assert fsm.current_state == SystemState.QUARANTINED

        # Expiration recovery
        fsm.transition_to(SystemState.HEALTHY, reason="Cooldown completed and fallback verified healthy")
        assert fsm.current_state == SystemState.HEALTHY

    def test_illegal_transitions_raise_error(self):
        fsm = PulseStateMachine(initial_state=SystemState.HEALTHY)

        # HEALTHY cannot jump straight to PROMOTED
        with pytest.raises(InvalidStateTransitionError):
            fsm.transition_to(SystemState.PROMOTED, reason="Invalid jump")

        # HEALTHY cannot jump straight to ROLLED_BACK
        with pytest.raises(InvalidStateTransitionError):
            fsm.transition_to(SystemState.ROLLED_BACK, reason="Invalid jump")

        # Transition to DEGRADED
        fsm.transition_to(SystemState.DEGRADED, reason="Drop")

        # DEGRADED cannot jump straight to CANARY without DIAGNOSING & EVALUATING
        with pytest.raises(InvalidStateTransitionError):
            fsm.transition_to(SystemState.CANARY, reason="Skipping evaluation")
