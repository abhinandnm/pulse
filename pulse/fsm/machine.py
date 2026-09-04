from datetime import datetime, timezone
from typing import List, Dict, Set, Optional, Callable
from pulse.domain.types import SystemState
from pulse.domain.events import StateTransitionEvent


class InvalidStateTransitionError(Exception):
    """Raised when an illegal FSM state transition is attempted."""
    pass


class PulseStateMachine:
    """
    Deterministic Finite State Machine for the Pulse platform.
    Enforces strict transitions between the 9 system states:
    HEALTHY, DEGRADED, DIAGNOSING, EVALUATING, CANARY, PROMOTED,
    ROLLED_BACK, QUARANTINED, ESCALATED.
    """

    ALLOWED_TRANSITIONS: Dict[SystemState, Set[SystemState]] = {
        SystemState.HEALTHY: {
            SystemState.DEGRADED,
        },
        SystemState.DEGRADED: {
            SystemState.DIAGNOSING,
            SystemState.HEALTHY,
            SystemState.ESCALATED,
        },
        SystemState.DIAGNOSING: {
            SystemState.EVALUATING,
            SystemState.ESCALATED,
            SystemState.DEGRADED,
        },
        SystemState.EVALUATING: {
            SystemState.CANARY,
            SystemState.QUARANTINED,
            SystemState.ESCALATED,
            SystemState.HEALTHY,
        },
        SystemState.CANARY: {
            SystemState.PROMOTED,
            SystemState.ROLLED_BACK,
            SystemState.ESCALATED,
        },
        SystemState.PROMOTED: {
            SystemState.HEALTHY,
            SystemState.DEGRADED,
        },
        SystemState.ROLLED_BACK: {
            SystemState.QUARANTINED,
            SystemState.ESCALATED,
            SystemState.HEALTHY,
        },
        SystemState.QUARANTINED: {
            SystemState.HEALTHY,
            SystemState.CANARY,
            SystemState.DEGRADED,
            SystemState.ESCALATED,
        },
        SystemState.ESCALATED: {
            SystemState.HEALTHY,
            SystemState.DIAGNOSING,
            SystemState.DEGRADED,
        },
    }

    def __init__(
        self,
        initial_state: SystemState = SystemState.HEALTHY,
        on_transition: Optional[Callable[[StateTransitionEvent], None]] = None,
    ):
        self._current_state = initial_state
        self._on_transition = on_transition
        self._history: List[StateTransitionEvent] = []

    @property
    def current_state(self) -> SystemState:
        return self._current_state

    @property
    def history(self) -> List[StateTransitionEvent]:
        return list(self._history)

    def can_transition(self, target_state: SystemState) -> bool:
        """Check if transition to target state is legally allowed from current state."""
        allowed = self.ALLOWED_TRANSITIONS.get(self._current_state, set())
        return target_state in allowed

    def transition_to(
        self,
        target_state: SystemState,
        reason: str,
        trigger: str = "AUTOMATIC",
        metadata: Optional[dict] = None,
    ) -> StateTransitionEvent:
        """
        Execute a state transition.
        Raises InvalidStateTransitionError if transition is illegal.
        """
        if not self.can_transition(target_state):
            raise InvalidStateTransitionError(
                f"Illegal FSM state transition from '{self._current_state.value}' to '{target_state.value}'. "
                f"Allowed target states: {[s.value for s in self.ALLOWED_TRANSITIONS.get(self._current_state, set())]}"
            )

        from_state = self._current_state
        self._current_state = target_state

        event = StateTransitionEvent(
            from_state=from_state,
            to_state=target_state,
            reason=reason,
            trigger=trigger,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

        self._history.append(event)

        if self._on_transition:
            self._on_transition(event)

        return event

    def reset_to_healthy(self, reason: str = "System reset to healthy baseline") -> StateTransitionEvent:
        """Direct administrative recovery to HEALTHY."""
        from_state = self._current_state
        self._current_state = SystemState.HEALTHY

        event = StateTransitionEvent(
            from_state=from_state,
            to_state=SystemState.HEALTHY,
            reason=reason,
            trigger="ADMIN_RESET",
            timestamp=datetime.now(timezone.utc),
        )
        self._history.append(event)
        return event
