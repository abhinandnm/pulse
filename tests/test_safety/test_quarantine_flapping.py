import pytest
from datetime import datetime, timezone, timedelta
from pulse.domain.types import RouteStatus
from pulse.safety.quarantine import QuarantineManager
from pulse.safety.anti_flapping import AntiFlappingController, HysteresisConfig


class TestQuarantineManager:
    def test_quarantine_cooldown_and_expiration(self):
        mgr = QuarantineManager(base_cooldown_seconds=10)
        route_id = "psp_faulty"

        rec = mgr.quarantine_route(route_id, reason="Timeout spike")
        assert mgr.is_quarantined(route_id) is True
        assert rec.cooldown_seconds == 10
        assert rec.quarantined_until > datetime.now(timezone.utc)

        # Manually release
        mgr.release_quarantine(route_id)
        assert mgr.is_quarantined(route_id) is False

    def test_exponential_backoff_on_repeat_quarantines(self):
        mgr = QuarantineManager(base_cooldown_seconds=60, max_cooldown_seconds=1800)
        route_id = "psp_repeat_offender"

        # Flap 1 -> 60s
        r1 = mgr.quarantine_route(route_id, reason="Drop 1")
        assert r1.cooldown_seconds == 60
        assert r1.flap_count == 1

        # Flap 2 -> 120s
        r2 = mgr.quarantine_route(route_id, reason="Drop 2")
        assert r2.cooldown_seconds == 120
        assert r2.flap_count == 2

        # Flap 3 -> 240s
        r3 = mgr.quarantine_route(route_id, reason="Drop 3")
        assert r3.cooldown_seconds == 240
        assert r3.flap_count == 3


class TestAntiFlappingAndHysteresis:
    def setup_method(self):
        self.config = HysteresisConfig(
            degrade_sr_threshold=0.85,
            recover_sr_threshold=0.95,
            degrade_latency_ms=1500.0,
            recover_latency_ms=400.0,
        )
        self.qm = QuarantineManager(base_cooldown_seconds=60)
        self.controller = AntiFlappingController(
            quarantine_manager=self.qm,
            hysteresis_config=self.config,
            flap_window_seconds=300,
            max_flaps_in_window=3,
        )

    def test_hysteresis_deadband(self):
        route_id = "psp_test_route"

        # 1. Healthy route at 98%
        s1 = self.controller.evaluate_route(route_id, current_sr=0.98, current_p95_latency_ms=150.0)
        assert s1 == RouteStatus.ACTIVE

        # 2. Slight dip to 90% (still above 85% degrade threshold) -> Stays ACTIVE
        s2 = self.controller.evaluate_route(route_id, current_sr=0.90, current_p95_latency_ms=250.0)
        assert s2 == RouteStatus.ACTIVE

        # 3. Severe drop to 75% (below 85%) -> Degrades to DEGRADED
        s3 = self.controller.evaluate_route(route_id, current_sr=0.75, current_p95_latency_ms=300.0)
        assert s3 == RouteStatus.DEGRADED

        # 4. Partial recovery to 92% (in deadband [85%, 95%]) -> Remains DEGRADED
        s4 = self.controller.evaluate_route(route_id, current_sr=0.92, current_p95_latency_ms=200.0)
        assert s4 == RouteStatus.DEGRADED

        # 5. Full recovery to 97% (exceeds 95%) -> Restored to ACTIVE
        s5 = self.controller.evaluate_route(route_id, current_sr=0.97, current_p95_latency_ms=180.0)
        assert s5 == RouteStatus.ACTIVE

    def test_anti_flapping_locks_route_in_quarantine(self):
        route_id = "psp_flapping_route"

        # Rapid flip 1: ACTIVE -> DEGRADED
        self.controller.evaluate_route(route_id, current_sr=0.70, current_p95_latency_ms=200.0)
        # Rapid flip 2: DEGRADED -> ACTIVE
        self.controller.evaluate_route(route_id, current_sr=0.98, current_p95_latency_ms=100.0)
        # Rapid flip 3: ACTIVE -> DEGRADED (Hits max flaps limit of 3!)
        s_final = self.controller.evaluate_route(route_id, current_sr=0.65, current_p95_latency_ms=200.0)

        # Flapping detected -> Locked into QUARANTINED!
        assert s_final == RouteStatus.QUARANTINED
        assert self.controller.is_flapping(route_id) is True
        assert self.qm.is_quarantined(route_id) is True
