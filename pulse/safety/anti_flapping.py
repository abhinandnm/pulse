from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import RouteStatus
from pulse.safety.quarantine import QuarantineManager


class HysteresisConfig(BaseModel):
    """Thresholds for hysteresis deadband to prevent oscillation."""
    model_config = ConfigDict(frozen=True)

    degrade_sr_threshold: float = Field(default=0.85, description="SR must drop below this to degrade (85%)")
    recover_sr_threshold: float = Field(default=0.95, description="SR must exceed this to recover (95%)")
    degrade_latency_ms: float = Field(default=1500.0, description="Latency must breach this to degrade")
    recover_latency_ms: float = Field(default=400.0, description="Latency must recover below this")


class AntiFlappingController:
    """
    Safety controller preventing route flapping and decision oscillation:
      1. Hysteresis deadbands: Separate trigger and recovery thresholds.
      2. Anti-flapping monitor: Detects rapid state flips within a sliding window.
      3. Automated quarantine backoff for chronic flapping routes.
    """

    def __init__(
        self,
        quarantine_manager: Optional[QuarantineManager] = None,
        hysteresis_config: Optional[HysteresisConfig] = None,
        flap_window_seconds: int = 300,
        max_flaps_in_window: int = 3,
    ):
        self.quarantine_manager = quarantine_manager or QuarantineManager()
        self.hysteresis = hysteresis_config or HysteresisConfig()
        self.flap_window_seconds = flap_window_seconds
        self.max_flaps_in_window = max_flaps_in_window

        # State tracking: route_id -> current RouteStatus
        self._route_states: Dict[str, RouteStatus] = {}
        # Flap history: route_id -> deque of (timestamp, from_status, to_status)
        self._status_transitions: Dict[str, deque[Tuple[datetime, RouteStatus, RouteStatus]]] = {}

    def get_route_status(self, route_id: str) -> RouteStatus:
        """Fetch current effective route status, checking quarantine first."""
        if self.quarantine_manager.is_quarantined(route_id):
            return RouteStatus.QUARANTINED
        return self._route_states.get(route_id, RouteStatus.ACTIVE)

    def evaluate_route(
        self,
        route_id: str,
        current_sr: float,
        current_p95_latency_ms: float,
    ) -> RouteStatus:
        """
        Evaluate route performance through hysteresis deadbands and anti-flapping gates.
        Returns the updated RouteStatus.
        """
        now = datetime.now(timezone.utc)

        # 1. Check if route is currently quarantined
        if self.quarantine_manager.is_quarantined(route_id):
            return RouteStatus.QUARANTINED

        current_status = self._route_states.get(route_id, RouteStatus.ACTIVE)
        new_status = current_status

        # 2. Hysteresis Deadband Evaluation
        cfg = self.hysteresis

        if current_status == RouteStatus.ACTIVE:
            # Requires significant drop below degrade threshold to transition to DEGRADED
            if current_sr < cfg.degrade_sr_threshold or current_p95_latency_ms > cfg.degrade_latency_ms:
                new_status = RouteStatus.DEGRADED

        elif current_status in (RouteStatus.DEGRADED, RouteStatus.STANDBY):
            # Requires strict recovery above recover threshold to return to ACTIVE
            if current_sr >= cfg.recover_sr_threshold and current_p95_latency_ms <= cfg.recover_latency_ms:
                new_status = RouteStatus.ACTIVE

        # 3. If a status change occurs, track it for anti-flapping
        if new_status != current_status:
            self._record_transition(route_id, current_status, new_status, now)
            self._route_states[route_id] = new_status

            # 4. Check if route is flapping
            if self.is_flapping(route_id):
                # Trigger automatic anti-flapping quarantine
                self.quarantine_manager.quarantine_route(
                    route_id=route_id,
                    reason=f"Anti-flapping triggered: {self.get_flap_count(route_id)} status flips within {self.flap_window_seconds}s",
                )
                self._route_states[route_id] = RouteStatus.QUARANTINED
                return RouteStatus.QUARANTINED

        return new_status

    def is_flapping(self, route_id: str) -> bool:
        """Return True if route has exceeded status changes limit in the time window."""
        self._prune_transitions(route_id)
        return len(self._status_transitions.get(route_id, [])) >= self.max_flaps_in_window

    def get_flap_count(self, route_id: str) -> int:
        self._prune_transitions(route_id)
        return len(self._status_transitions.get(route_id, []))

    def _record_transition(
        self,
        route_id: str,
        from_status: RouteStatus,
        to_status: RouteStatus,
        timestamp: datetime,
    ) -> None:
        if route_id not in self._status_transitions:
            self._status_transitions[route_id] = deque()
        self._status_transitions[route_id].append((timestamp, from_status, to_status))
        self._prune_transitions(route_id)

    def _prune_transitions(self, route_id: str) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self.flap_window_seconds)
        queue = self._status_transitions.get(route_id)
        if queue:
            while queue and queue[0][0] < cutoff:
                queue.popleft()
