import pytest
from pulse.domain.types import ActionType, RouteStatus, Bank
from pulse.domain.telemetry import TelemetrySnapshot
from pulse.domain.route import RouteHealth
from pulse.counterfactual.engine import CounterfactualEngine


class TestCounterfactualEngine:
    def setup_method(self):
        self.engine = CounterfactualEngine()

    def test_evaluates_all_options_on_degradation(self):
        # psp_hdfc_direct is degraded with 60% success rate
        route_h = {
            "psp_hdfc_direct": RouteHealth(
                route_id="psp_hdfc_direct",
                status=RouteStatus.DEGRADED,
                success_rate=0.60,
                error_rate=0.40,
                timeout_rate=0.30,
            ),
            "psp_icici_backup": RouteHealth(
                route_id="psp_icici_backup",
                status=RouteStatus.ACTIVE,
                success_rate=0.98,
                error_rate=0.02,
                timeout_rate=0.01,
            ),
            "psp_aggregator_fallback": RouteHealth(
                route_id="psp_aggregator_fallback",
                status=RouteStatus.ACTIVE,
                success_rate=0.97,
                error_rate=0.03,
                timeout_rate=0.01,
            ),
        }
        snap = TelemetrySnapshot(
            window_seconds=60,
            total_transactions=100,
            successful_transactions=60,
            failed_transactions=40,
            success_rate=0.60,
            route_health=route_h,
        )

        decision = self.engine.evaluate_options(
            snapshot=snap,
            degraded_route_id="psp_hdfc_direct",
        )

        actions_evaluated = {c.action for c in decision.evaluated_candidates}

        # Must evaluate all core options specified in BRICKS.txt
        assert ActionType.NO_ACTION in actions_evaluated
        assert ActionType.SWITCH_ROUTE in actions_evaluated
        assert ActionType.SPLIT_TRAFFIC_CANARY in actions_evaluated
        assert ActionType.QUARANTINE_ROUTE in actions_evaluated
        assert ActionType.ESCALATE_HUMAN in actions_evaluated

        # Candidates must be strictly sorted by utility descending
        scores = [c.utility_score for c in decision.evaluated_candidates]
        assert scores == sorted(scores, reverse=True)

        # Chosen action must be either SPLIT_TRAFFIC_CANARY or QUARANTINE_ROUTE (safest high utility)
        assert decision.chosen_action in (ActionType.SPLIT_TRAFFIC_CANARY, ActionType.QUARANTINE_ROUTE)
        assert decision.chosen_route_id in ("psp_icici_backup", "psp_aggregator_fallback")
        assert decision.projected_revenue_recovery_inr > 0.0

    def test_healthy_state_ranks_no_action_high(self):
        # 99% success rate across system
        snap = TelemetrySnapshot(
            window_seconds=60,
            total_transactions=100,
            successful_transactions=99,
            failed_transactions=1,
            success_rate=0.99,
        )
        decision = self.engine.evaluate_options(snapshot=snap)
        no_action_candidate = next(c for c in decision.evaluated_candidates if c.action == ActionType.NO_ACTION)
        assert no_action_candidate.utility_score >= 95.0
