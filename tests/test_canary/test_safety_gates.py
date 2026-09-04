import pytest
from pulse.domain.types import Bank, PaymentMethod, ErrorCode, CanaryGateStatus
from pulse.domain.transaction import Transaction, TransactionResult
from pulse.domain.canary import CanaryConfig, CanaryState
from pulse.canary.controller import CanarySafetyController


def make_results(
    count: int,
    success_rate: float = 0.98,
    latency_ms: float = 120.0,
    error_code: ErrorCode = ErrorCode.NONE,
) -> list:
    succ = int(count * success_rate)
    res = []
    for i in range(count):
        is_succ = i < succ
        txn = Transaction(
            transaction_id=f"canary_txn_{i}",
            amount_inr=500.0,
            bank=Bank.HDFC,
            payment_method=PaymentMethod.UPI,
            route_id="psp_candidate",
        )
        res.append(
            TransactionResult(
                transaction=txn,
                success=is_succ,
                latency_ms=latency_ms,
                error_code=ErrorCode.NONE if is_succ else error_code,
            )
        )
    return res


class TestCanarySafetyController:
    def setup_method(self):
        self.config = CanaryConfig(
            target_route_id="psp_candidate",
            traffic_stages=[20, 50, 100],
            min_sample_size=25,
            min_success_rate=0.90,
            max_p95_latency_ms=1000.0,
            max_error_rate=0.08,
        )
        self.controller = CanarySafetyController(config=self.config)

    def test_sample_size_gate_pending(self):
        state = CanaryState(target_route_id="psp_candidate", fallback_route_id="psp_fallback")
        results = make_results(count=15, success_rate=1.0)  # Only 15, needs 25

        new_state, eval_res = self.controller.evaluate_results(state, results)
        assert eval_res.status == CanaryGateStatus.PENDING
        assert eval_res.should_promote_stage is False
        assert eval_res.should_rollback is False
        assert new_state.status == CanaryGateStatus.PENDING

    def test_progressive_promotion_stages(self):
        # Stage 0: 20%
        state = CanaryState(
            target_route_id="psp_candidate",
            fallback_route_id="psp_fallback",
            current_traffic_percentage=20,
            current_stage_index=0,
        )
        stage0_results = make_results(count=30, success_rate=0.97, latency_ms=150.0)

        # Passes Stage 0 -> advances to 50%
        state1, eval1 = self.controller.evaluate_results(state, stage0_results)
        assert eval1.status == CanaryGateStatus.PASSED
        assert eval1.should_promote_stage is True
        assert eval1.next_traffic_percentage == 50
        assert state1.current_traffic_percentage == 50
        assert state1.current_stage_index == 1

        # Stage 1: 50% passes -> advances to 100%
        stage1_results = make_results(count=30, success_rate=0.96, latency_ms=180.0)
        state2, eval2 = self.controller.evaluate_results(state1, stage1_results)
        assert eval2.status == CanaryGateStatus.PASSED
        assert eval2.should_promote_stage is True
        assert eval2.next_traffic_percentage == 100
        assert state2.current_traffic_percentage == 100
        assert state2.current_stage_index == 2

        # Stage 2: 100% passes -> FULL PROMOTION!
        stage2_results = make_results(count=30, success_rate=0.97, latency_ms=150.0)
        state3, eval3 = self.controller.evaluate_results(state2, stage2_results)
        assert eval3.status == CanaryGateStatus.PASSED
        assert eval3.should_promote_full is True
        assert state3.promoted is True
        assert state3.current_traffic_percentage == 100

    def test_gate_failure_triggers_immediate_rollback(self):
        state = CanaryState(
            target_route_id="psp_candidate",
            fallback_route_id="psp_fallback",
            current_traffic_percentage=20,
            current_stage_index=0,
        )

        # High error rate: only 70% success (cap is 8% error rate)
        bad_results = make_results(count=30, success_rate=0.70, error_code=ErrorCode.GATEWAY_ERROR)

        new_state, eval_res = self.controller.evaluate_results(state, bad_results)
        assert eval_res.status == CanaryGateStatus.FAILED
        assert eval_res.should_rollback is True
        assert eval_res.next_traffic_percentage == 0
        assert new_state.rolled_back is True
        assert any(g.gate_name == "ERROR_RATE_CAP" and not g.passed for g in eval_res.gates)

    def test_latency_slo_breach_triggers_rollback(self):
        state = CanaryState(
            target_route_id="psp_candidate",
            fallback_route_id="psp_fallback",
            current_traffic_percentage=50,
            current_stage_index=1,
        )

        # High latency: 2500ms (SLO cap is 1000ms)
        slow_results = make_results(count=30, success_rate=0.95, latency_ms=2500.0)

        new_state, eval_res = self.controller.evaluate_results(state, slow_results)
        assert eval_res.should_rollback is True
        assert new_state.rolled_back is True
        assert any(g.gate_name == "LATENCY_SLO" and not g.passed for g in eval_res.gates)
