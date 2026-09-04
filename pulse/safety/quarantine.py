from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import RouteStatus


class QuarantineRecord(BaseModel):
    """Record of a route placed in quarantine cooldown."""
    model_config = ConfigDict(frozen=True)

    route_id: str
    quarantined_at: datetime
    quarantined_until: datetime
    reason: str
    cooldown_seconds: int
    flap_count: int = 0


class QuarantineManager:
    """
    Manages route quarantine cooldowns, exponential backoff for repeat offenders,
    and safe post-quarantine release into STANDBY.
    """

    def __init__(self, base_cooldown_seconds: int = 60, max_cooldown_seconds: int = 1800):
        self.base_cooldown = base_cooldown_seconds
        self.max_cooldown = max_cooldown_seconds
        self._quarantined: Dict[str, QuarantineRecord] = {}
        self._flap_history: Dict[str, int] = {}  # route_id -> count of quarantine events

    def quarantine_route(
        self,
        route_id: str,
        reason: str,
        custom_cooldown: Optional[int] = None,
    ) -> QuarantineRecord:
        """Place a route in quarantine with exponential backoff for repeated failures."""
        now = datetime.now(timezone.utc)
        flaps = self._flap_history.get(route_id, 0) + 1
        self._flap_history[route_id] = flaps

        # Exponential backoff: base * 2^(flaps - 1)
        if custom_cooldown:
            duration = custom_cooldown
        else:
            duration = min(self.max_cooldown, int(self.base_cooldown * (2 ** (flaps - 1))))

        until = now + timedelta(seconds=duration)
        record = QuarantineRecord(
            route_id=route_id,
            quarantined_at=now,
            quarantined_until=until,
            reason=reason,
            cooldown_seconds=duration,
            flap_count=flaps,
        )
        self._quarantined[route_id] = record
        return record

    def is_quarantined(self, route_id: str) -> bool:
        """Return True if route is currently in quarantine."""
        rec = self._quarantined.get(route_id)
        if not rec:
            return False
        now = datetime.now(timezone.utc)
        if now >= rec.quarantined_until:
            # Cooldown expired -> remove from quarantine
            del self._quarantined[route_id]
            return False
        return True

    def get_quarantine_record(self, route_id: str) -> Optional[QuarantineRecord]:
        if self.is_quarantined(route_id):
            return self._quarantined.get(route_id)
        return None

    def release_quarantine(self, route_id: str) -> None:
        """Manually release route from quarantine."""
        self._quarantined.pop(route_id, None)

    def reset_flap_count(self, route_id: str) -> None:
        """Reset flap count after prolonged healthy operation."""
        self._flap_history.pop(route_id, None)
