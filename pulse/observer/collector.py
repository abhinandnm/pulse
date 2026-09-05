from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List
from pulse.domain.transaction import TransactionResult
from pulse.domain.route import RouteHealth
from pulse.domain.telemetry import TelemetrySnapshot
from pulse.observer.window import SlidingWindow
from pulse.observer.metrics import MetricsCalculator
from pulse.observer.baseline import BaselineManager, BaselineProfile


class TelemetryObserver:
    """
    Central telemetry collector and observer engine.
    Ingests payment results, maintains sliding window metrics,
    and publishes updated TelemetrySnapshots.
    """

    def __init__(
        self,
        window_seconds: int = 60,
        baseline_manager: Optional[BaselineManager] = None,
    ):
        self.window_seconds = window_seconds
        self.window = SlidingWindow(window_seconds=window_seconds)
        self.baseline_manager = baseline_manager or BaselineManager()
        self.quarantined_routes: Dict[str, datetime] = {}
        self._last_snapshot: Optional[TelemetrySnapshot] = None

    def record_transaction(self, result: TransactionResult) -> None:
        """Ingest a payment transaction outcome."""
        self.window.add(result)

    def record_batch(self, results: List[TransactionResult]) -> None:
        """Ingest multiple transaction outcomes."""
        for r in results:
            self.window.add(r)

    def quarantine_route(self, route_id: str, cooldown_seconds: int = 60) -> None:
        """Place a degraded route into quarantine with an expiration timer."""
        until = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
        self.quarantined_routes[route_id] = until

    def release_quarantine(self, route_id: str) -> None:
        """Release a route from quarantine."""
        self.quarantined_routes.pop(route_id, None)

    def is_route_quarantined(self, route_id: str) -> bool:
        """Check if route is actively quarantined."""
        until = self.quarantined_routes.get(route_id)
        if not until:
            return False
        if datetime.now(timezone.utc) >= until:
            del self.quarantined_routes[route_id]
            return False
        return True

    def clear(self) -> None:
        """Empty the window and clear quarantines."""
        self.window.clear()
        self.quarantined_routes.clear()
        self._last_snapshot = None

    def get_snapshot(self) -> TelemetrySnapshot:
        """Compute and return real-time TelemetrySnapshot for the sliding window."""
        results = self.window.get_results()
        snapshot = MetricsCalculator.compute_snapshot(
            results=results,
            window_seconds=self.window_seconds,
            quarantined_routes=self.quarantined_routes,
        )
        self._last_snapshot = snapshot
        return snapshot

    def get_route_health(self, route_id: str) -> Optional[RouteHealth]:
        """Fetch real-time health for a specific route."""
        snapshot = self.get_snapshot()
        return snapshot.route_health.get(route_id)

    def get_baseline(self) -> BaselineProfile:
        return self.baseline_manager.get_system_baseline()

    def get_route_baseline(self, route_id: str) -> BaselineProfile:
        return self.baseline_manager.get_route_baseline(route_id)
