from datetime import datetime, timezone
from typing import List, Optional, Dict
from pulse.domain.types import ActionType, RouteStatus, Bank
from pulse.domain.telemetry import TelemetrySnapshot
from pulse.domain.route import PaymentRoute, RouteHealth
from pulse.domain.counterfactual import CandidateEvaluation, CounterfactualDecision
from pulse.simulator.routes import DEFAULT_ROUTES, get_route
from pulse.observer.baseline import BaselineManager


class CounterfactualEngine:
    """
    Simulates and ranks potential recovery interventions before execution.
    Computes expected success rate lift, blast radius risk, and processing
    fee impact to choose the optimal recovery path.
    """

    def __init__(self, baseline_manager: Optional[BaselineManager] = None):
        self.baseline_manager = baseline_manager or BaselineManager()

    def evaluate_options(
        self,
        snapshot: TelemetrySnapshot,
        degraded_route_id: Optional[str] = None,
        affected_bank: Optional[Bank] = None,
        available_routes: Optional[Dict[str, PaymentRoute]] = None,
        incident_id: Optional[str] = None,
    ) -> CounterfactualDecision:
        """Evaluate candidate recovery actions and return the highest-utility decision."""
        routes = available_routes or DEFAULT_ROUTES
        system_baseline = self.baseline_manager.get_system_baseline()
        current_sr = snapshot.success_rate
        candidates: List[CandidateEvaluation] = []

        # Current route info
        current_route = routes.get(degraded_route_id) if degraded_route_id else None
        current_cost = current_route.cost_per_txn_inr if current_route else 0.20

        # Candidate 1: NO_ACTION
        sr_bleed = max(0.0, system_baseline.expected_success_rate - current_sr)
        no_action_risk = min(1.0, sr_bleed * 3.0)
        candidates.append(
            CandidateEvaluation(
                action=ActionType.NO_ACTION,
                expected_sr_lift=0.0,
                estimated_cost_delta_inr=0.0,
                risk_score=round(no_action_risk, 2),
                utility_score=round(max(0.0, 100.0 - (no_action_risk * 100.0)), 2),
                rationale="Maintain current routing. High risk of continued financial exposure if degraded.",
            )
        )

        # Candidate 2 & 3: Evaluate healthy alternate routes for SWITCH_ROUTE & CANARY
        for route_id, route in routes.items():
            # Skip aliases and the currently degraded route
            if route_id in ("PSP_A", "PSP_B", "PSP_C") or route_id == degraded_route_id:
                continue

            r_health = snapshot.route_health.get(route_id)
            if r_health and (r_health.status == RouteStatus.QUARANTINED or r_health.success_rate < 0.90):
                continue  # Skip degraded or quarantined alternates

            r_baseline = self.baseline_manager.get_route_baseline(route_id)
            expected_lift = max(0.0, r_baseline.expected_success_rate - current_sr)
            cost_delta = round(route.cost_per_txn_inr - current_cost, 2)

            # Option A: Full Instant Switch (high blast radius risk)
            switch_risk = 0.45
            switch_utility = round((expected_lift * 100.0) - (switch_risk * 30.0) - (max(0.0, cost_delta) * 5.0), 2)
            candidates.append(
                CandidateEvaluation(
                    action=ActionType.SWITCH_ROUTE,
                    target_route_id=route_id,
                    expected_sr_lift=round(expected_lift, 4),
                    estimated_cost_delta_inr=cost_delta,
                    risk_score=switch_risk,
                    utility_score=switch_utility,
                    rationale=f"Instant 100% reroute to {route.name}. Fast recovery but high blast radius if {route_id} saturates.",
                )
            )

            # Option B: Progressive Canary Split (safest blast radius)
            canary_risk = 0.10
            canary_lift = round(expected_lift, 4)
            # Canary gets safety bonus of +15 utility for progressive gating
            canary_utility = round((canary_lift * 100.0) - (canary_risk * 30.0) - (max(0.0, cost_delta) * 5.0) + 15.0, 2)
            candidates.append(
                CandidateEvaluation(
                    action=ActionType.SPLIT_TRAFFIC_CANARY,
                    target_route_id=route_id,
                    expected_sr_lift=canary_lift,
                    estimated_cost_delta_inr=cost_delta,
                    risk_score=canary_risk,
                    utility_score=canary_utility,
                    rationale=f"Progressive Canary (20% -> 50% -> 100%) to {route.name}. Safe validation across 5 health gates.",
                )
            )

            # Option C: Quarantine Degraded Route & Divert
            if degraded_route_id:
                quarantine_risk = 0.20
                quarantine_utility = round((expected_lift * 100.0) - (quarantine_risk * 30.0) + 10.0, 2)
                candidates.append(
                    CandidateEvaluation(
                        action=ActionType.QUARANTINE_ROUTE,
                        target_route_id=route_id,
                        expected_sr_lift=round(expected_lift, 4),
                        estimated_cost_delta_inr=cost_delta,
                        risk_score=quarantine_risk,
                        utility_score=quarantine_utility,
                        rationale=f"Place {degraded_route_id} in 60s cooldown quarantine and divert traffic to {route.name}.",
                    )
                )

        # Candidate 4: Escalate to Human (if all alternatives are unhealthy or SR bleed extreme)
        escalate_utility = 15.0 if current_sr < 0.60 else 5.0
        candidates.append(
            CandidateEvaluation(
                action=ActionType.ESCALATE_HUMAN,
                expected_sr_lift=0.0,
                estimated_cost_delta_inr=0.0,
                risk_score=0.05,
                utility_score=escalate_utility,
                rationale="Escalate to on-call payment engineering team for manual intervention.",
            )
        )

        # Rank candidates strictly by utility_score descending
        ranked = sorted(candidates, key=lambda c: c.utility_score, reverse=True)
        chosen = ranked[0]

        # Financial recovery projection (AOV ~ 1200 INR * 100 TPM * 60 min * SR Lift)
        projected_recovery = round(chosen.expected_sr_lift * snapshot.total_transactions * 1200.0, 2)

        return CounterfactualDecision(
            incident_id=incident_id,
            evaluated_candidates=ranked,
            chosen_action=chosen.action,
            chosen_route_id=chosen.target_route_id,
            projected_revenue_recovery_inr=projected_recovery,
            explanation=f"Selected {chosen.action.value} (utility: {chosen.utility_score}) target: {chosen.target_route_id}. {chosen.rationale}",
        )
