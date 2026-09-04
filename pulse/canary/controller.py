from datetime import datetime, timezone
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import CanaryGateStatus
from pulse.domain.transaction import TransactionResult
from pulse.domain.canary import CanaryGate, CanaryConfig, CanaryState
from pulse.observer.metrics import compute_wilson_interval, compute_latency_metrics


class CanaryEvaluationResult(BaseModel):
    """Outcome of evaluating canary safety gates for the current stage."""
    model_config = ConfigDict(frozen=True)

    status: CanaryGateStatus
    should_promote_stage: bool = False
    should_promote_full: bool = False
    should_rollback: bool = False
    next_traffic_percentage: int = 20
    gates: List[CanaryGate] = Field(default_factory=list)
    reason: str = ""


class CanarySafetyController:
    """
    Deterministic safety controller managing progressive canary rollouts.
    Evaluates 5 safety gates across traffic stages (20% -> 50% -> 100%):
      1. Minimum sample size
      2. Success-rate delta
      3. Wilson lower-bound comparison
      4. Latency SLO
      5. Error-rate cap
    """

    def __init__(self, config: Optional[CanaryConfig] = None):
        self.config = config or CanaryConfig(
            target_route_id="default_candidate",
            traffic_stages=[20, 50, 100],
            min_sample_size=20,
            min_success_rate=0.90,
            max_p95_latency_ms=1200.0,
            max_error_rate=0.08,
        )

    def evaluate_results(
        self,
        canary_state: CanaryState,
        candidate_results: List[TransactionResult],
    ) -> Tuple[CanaryState, CanaryEvaluationResult]:
        """
        Evaluate candidate route transaction results against the 5 deterministic safety gates.
        Returns the updated CanaryState and evaluation summary.
        """
        total = len(candidate_results)
        cfg = self.config

        # 1. Gate 1: Minimum Sample Size
        gate_sample_passed = total >= cfg.min_sample_size
        gate_sample = CanaryGate(
            gate_name="MIN_SAMPLE_SIZE",
            status=CanaryGateStatus.PASSED if gate_sample_passed else CanaryGateStatus.PENDING,
            threshold=float(cfg.min_sample_size),
            observed_value=float(total),
            passed=gate_sample_passed,
            message=f"Sample size {total}/{cfg.min_sample_size}",
        )

        if not gate_sample_passed:
            # Insufficient sample size to make promotion or rollback decision
            eval_result = CanaryEvaluationResult(
                status=CanaryGateStatus.PENDING,
                should_promote_stage=False,
                should_promote_full=False,
                should_rollback=False,
                next_traffic_percentage=canary_state.current_traffic_percentage,
                gates=[gate_sample],
                reason=f"Awaiting minimum sample size ({total}/{cfg.min_sample_size})",
            )
            updated_state = CanaryState(
                canary_id=canary_state.canary_id,
                target_route_id=canary_state.target_route_id,
                fallback_route_id=canary_state.fallback_route_id,
                current_traffic_percentage=canary_state.current_traffic_percentage,
                current_stage_index=canary_state.current_stage_index,
                status=CanaryGateStatus.PENDING,
                gates=[gate_sample],
                started_at=canary_state.started_at,
                updated_at=datetime.now(timezone.utc),
            )
            return updated_state, eval_result

        # Calculate metrics from candidate results
        successes = sum(1 for r in candidate_results if r.success)
        failures = total - successes
        sr = successes / total
        er = failures / total
        ci = compute_wilson_interval(successes, total)
        latencies = [r.latency_ms for r in candidate_results]
        lat_metrics = compute_latency_metrics(latencies)

        # 2. Gate 2: Success Rate Threshold
        gate_sr_passed = sr >= cfg.min_success_rate
        gate_sr = CanaryGate(
            gate_name="SUCCESS_RATE_DELTA",
            status=CanaryGateStatus.PASSED if gate_sr_passed else CanaryGateStatus.FAILED,
            threshold=cfg.min_success_rate,
            observed_value=round(sr, 4),
            passed=gate_sr_passed,
            message=f"Success rate {round(sr * 100, 1)}% vs min {round(cfg.min_success_rate * 100, 1)}%",
        )

        # 3. Gate 3: Wilson Confidence Lower Bound (statistically reliable performance)
        wilson_threshold = max(0.70, cfg.min_success_rate - 0.15)
        gate_wilson_passed = ci.lower >= wilson_threshold
        gate_wilson = CanaryGate(
            gate_name="WILSON_LOWER_BOUND",
            status=CanaryGateStatus.PASSED if gate_wilson_passed else CanaryGateStatus.FAILED,
            threshold=round(wilson_threshold, 4),
            observed_value=ci.lower,
            passed=gate_wilson_passed,
            message=f"Wilson 95% lower bound {ci.lower} vs threshold {round(wilson_threshold, 4)}",
        )

        # 4. Gate 4: Latency SLO
        gate_lat_passed = lat_metrics.p95_ms <= cfg.max_p95_latency_ms
        gate_lat = CanaryGate(
            gate_name="LATENCY_SLO",
            status=CanaryGateStatus.PASSED if gate_lat_passed else CanaryGateStatus.FAILED,
            threshold=cfg.max_p95_latency_ms,
            observed_value=lat_metrics.p95_ms,
            passed=gate_lat_passed,
            message=f"p95 latency {lat_metrics.p95_ms}ms vs SLO {cfg.max_p95_latency_ms}ms",
        )

        # 5. Gate 5: Error Rate Cap
        gate_er_passed = er <= cfg.max_error_rate
        gate_er = CanaryGate(
            gate_name="ERROR_RATE_CAP",
            status=CanaryGateStatus.PASSED if gate_er_passed else CanaryGateStatus.FAILED,
            threshold=cfg.max_error_rate,
            observed_value=round(er, 4),
            passed=gate_er_passed,
            message=f"Error rate {round(er * 100, 1)}% vs cap {round(cfg.max_error_rate * 100, 1)}%",
        )

        all_gates = [gate_sample, gate_sr, gate_wilson, gate_lat, gate_er]
        failed_gates = [g for g in all_gates if not g.passed]

        now = datetime.now(timezone.utc)

        if failed_gates:
            # Immediate Rollback trigger
            fail_msg = "; ".join(f"{g.gate_name}: {g.message}" for g in failed_gates)
            eval_result = CanaryEvaluationResult(
                status=CanaryGateStatus.FAILED,
                should_promote_stage=False,
                should_promote_full=False,
                should_rollback=True,
                next_traffic_percentage=0,
                gates=all_gates,
                reason=f"Canary gate failure triggered rollback: {fail_msg}",
            )
            updated_state = CanaryState(
                canary_id=canary_state.canary_id,
                target_route_id=canary_state.target_route_id,
                fallback_route_id=canary_state.fallback_route_id,
                current_traffic_percentage=0,
                current_stage_index=canary_state.current_stage_index,
                status=CanaryGateStatus.FAILED,
                gates=all_gates,
                started_at=canary_state.started_at,
                updated_at=now,
                rolled_back=True,
            )
            return updated_state, eval_result

        # All 5 gates passed! Check stage progression
        current_idx = canary_state.current_stage_index
        stages = cfg.traffic_stages

        if current_idx + 1 < len(stages):
            # Advance to next stage (e.g. 20% -> 50%)
            next_pct = stages[current_idx + 1]
            eval_result = CanaryEvaluationResult(
                status=CanaryGateStatus.PASSED,
                should_promote_stage=True,
                should_promote_full=False,
                should_rollback=False,
                next_traffic_percentage=next_pct,
                gates=all_gates,
                reason=f"Passed stage {current_idx} ({stages[current_idx]}%). Advancing to {next_pct}%.",
            )
            updated_state = CanaryState(
                canary_id=canary_state.canary_id,
                target_route_id=canary_state.target_route_id,
                fallback_route_id=canary_state.fallback_route_id,
                current_traffic_percentage=next_pct,
                current_stage_index=current_idx + 1,
                status=CanaryGateStatus.PASSED,
                gates=all_gates,
                started_at=canary_state.started_at,
                updated_at=now,
            )
            return updated_state, eval_result
        else:
            # Final stage (100%) passed -> FULL PROMOTION!
            eval_result = CanaryEvaluationResult(
                status=CanaryGateStatus.PASSED,
                should_promote_stage=False,
                should_promote_full=True,
                should_rollback=False,
                next_traffic_percentage=100,
                gates=all_gates,
                reason="All canary stages and safety gates verified. Route promoted to 100% active traffic.",
            )
            updated_state = CanaryState(
                canary_id=canary_state.canary_id,
                target_route_id=canary_state.target_route_id,
                fallback_route_id=canary_state.fallback_route_id,
                current_traffic_percentage=100,
                current_stage_index=current_idx,
                status=CanaryGateStatus.PASSED,
                gates=all_gates,
                started_at=canary_state.started_at,
                updated_at=now,
                promoted=True,
            )
            return updated_state, eval_result
