import pytest
from pulse.domain.types import Bank, PaymentMethod, ErrorCode, PaymentState
from pulse.domain.route import PaymentRoute
from pulse.simulator.failures import FailureScenarioType, create_failure_profile
from pulse.simulator.routes import (
    DEFAULT_ROUTES,
    PSP_HDFC_DIRECT,
    PSP_AGGREGATOR_FALLBACK,
    get_route,
    get_eligible_routes,
)
from pulse.simulator.generator import (
    generate_transaction,
    execute_transaction,
    generate_amount_for_method,
)
from pulse.simulator.scenarios import PaymentScenarioRunner


class TestDeterministicReproduction:
    def test_same_seed_produces_identical_transactions(self):
        """CRITICAL COMPLETION REQUIREMENT: The same seed must reproduce the same scenario."""
        runner1 = PaymentScenarioRunner(seed=101)
        runner2 = PaymentScenarioRunner(seed=101)

        results1 = runner1.run_scenario(FailureScenarioType.PSP_TIMEOUT, count=30)
        results2 = runner2.run_scenario(FailureScenarioType.PSP_TIMEOUT, count=30)

        assert len(results1) == len(results2) == 30

        for r1, r2 in zip(results1, results2):
            assert r1.transaction.transaction_id == r2.transaction.transaction_id
            assert r1.transaction.amount_inr == r2.transaction.amount_inr
            assert r1.transaction.bank == r2.transaction.bank
            assert r1.transaction.payment_method == r2.transaction.payment_method
            assert r1.success == r2.success
            assert r1.latency_ms == r2.latency_ms
            assert r1.error_code == r2.error_code
            assert r1.payment_state == r2.payment_state

    def test_different_seeds_produce_different_sequences(self):
        runner1 = PaymentScenarioRunner(seed=101)
        runner2 = PaymentScenarioRunner(seed=999)

        results1 = runner1.run_scenario(FailureScenarioType.HEALTHY, count=10)
        results2 = runner2.run_scenario(FailureScenarioType.HEALTHY, count=10)

        # Transaction IDs must differ
        ids1 = [r.transaction.transaction_id for r in results1]
        ids2 = [r.transaction.transaction_id for r in results2]
        assert ids1 != ids2


class TestRouteCapabilities:
    def test_route_capability_enforcement(self):
        """Transactions to routes with unsupported banks/methods must be rejected."""
        hdfc_route = PSP_HDFC_DIRECT  # Only supports HDFC Bank, UPI & NetBanking
        
        # Test unsupported bank (SBI)
        txn_sbi = generate_transaction(route_id=hdfc_route.route_id, bank=Bank.SBI, payment_method=PaymentMethod.UPI)
        result = execute_transaction(txn_sbi, hdfc_route)
        assert result.success is False
        assert result.error_code == ErrorCode.GATEWAY_ERROR
        assert "does not support" in result.error_message

        # Test unsupported method (CARD)
        txn_card = generate_transaction(route_id=hdfc_route.route_id, bank=Bank.HDFC, payment_method=PaymentMethod.CARD)
        result = execute_transaction(txn_card, hdfc_route)
        assert result.success is False
        assert result.error_code == ErrorCode.GATEWAY_ERROR

    def test_get_eligible_routes(self):
        routes_hdfc_upi = get_eligible_routes(Bank.HDFC, PaymentMethod.UPI)
        assert len(routes_hdfc_upi) == 3  # All 3 support HDFC UPI

        routes_sbi_card = get_eligible_routes(Bank.SBI, PaymentMethod.CARD)
        assert len(routes_sbi_card) == 1
        assert routes_sbi_card[0].route_id == "psp_aggregator_fallback"


class TestFailureScenarios:
    def test_psp_timeout_scenario(self):
        runner = PaymentScenarioRunner(seed=42)
        results = runner.run_scenario(
            FailureScenarioType.PSP_TIMEOUT,
            count=50,
            target_route_id="psp_aggregator_fallback",
        )
        timeouts = [r for r in results if r.error_code == ErrorCode.PSP_TIMEOUT]
        assert len(timeouts) > 30  # High failure probability
        for t in timeouts:
            assert t.latency_ms >= 3000.0
            assert t.payment_state == PaymentState.UNKNOWN

    def test_bank_degradation_scenario(self):
        runner = PaymentScenarioRunner(seed=42)
        results = runner.run_scenario(
            FailureScenarioType.BANK_DEGRADATION,
            count=50,
            target_route_id="psp_aggregator_fallback",
            target_bank=Bank.ICICI,
        )
        issuer_down = [r for r in results if r.error_code == ErrorCode.ISSUER_DOWN and r.transaction.bank == Bank.ICICI]
        assert len(issuer_down) > 20

    def test_auth_spike_scenario(self):
        runner = PaymentScenarioRunner(seed=42)
        results = runner.run_scenario(
            FailureScenarioType.AUTH_SPIKE,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        auth_failures = [r for r in results if r.error_code == ErrorCode.AUTH_FAILED]
        assert len(auth_failures) > 20

    def test_http_500_scenario(self):
        runner = PaymentScenarioRunner(seed=42)
        results = runner.run_scenario(
            FailureScenarioType.HTTP_500,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        gateway_errors = [r for r in results if r.error_code == ErrorCode.GATEWAY_ERROR]
        assert len(gateway_errors) > 25

    def test_network_reset_scenario(self):
        runner = PaymentScenarioRunner(seed=42)
        results = runner.run_scenario(
            FailureScenarioType.NETWORK_RESET,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        resets = [r for r in results if r.error_code == ErrorCode.NETWORK_RESET]
        assert len(resets) > 20
        for r in resets:
            assert r.latency_ms <= 60.0  # Network reset is extremely fast

    def test_traffic_surge_scenario(self):
        runner = PaymentScenarioRunner(seed=42)
        results = runner.run_scenario(
            FailureScenarioType.TRAFFIC_SURGE,
            count=20,
            target_route_id="psp_aggregator_fallback",
        )
        # 5x multiplier means count is 100
        assert len(results) == 100
        rate_limited = [r for r in results if r.error_code == ErrorCode.RATE_LIMITED]
        assert len(rate_limited) > 30

    def test_route_flapping_scenario(self):
        runner = PaymentScenarioRunner(seed=42)
        results = runner.run_scenario(
            FailureScenarioType.ROUTE_FLAPPING,
            count=40,
            target_route_id="psp_aggregator_fallback",
        )
        # Cycle size 10 means batch 0-9 is healthy, 10-19 has failures, 20-29 is healthy, etc.
        batch1 = results[0:10]
        batch2 = results[10:20]

        batch1_failures = [r for r in batch1 if not r.success]
        batch2_failures = [r for r in batch2 if not r.success]

        assert len(batch1_failures) <= 1  # Baseline healthy
        assert len(batch2_failures) >= 6  # Degraded phase of flap

    def test_mid_canary_failure_scenario(self):
        runner = PaymentScenarioRunner(seed=42)

        # Under 20% canary traffic -> route behaves healthy
        early_results = runner.run_scenario(
            FailureScenarioType.MID_CANARY_FAILURE,
            count=30,
            target_route_id="psp_aggregator_fallback",
            canary_traffic_pct=20,
        )
        early_failures = [r for r in early_results if r.error_code == ErrorCode.PSP_TIMEOUT]
        assert len(early_failures) == 0

        # At 50% canary traffic -> route fails under load
        late_results = runner.run_scenario(
            FailureScenarioType.MID_CANARY_FAILURE,
            count=30,
            target_route_id="psp_aggregator_fallback",
            canary_traffic_pct=50,
        )
        late_failures = [r for r in late_results if r.error_code == ErrorCode.PSP_TIMEOUT]
        assert len(late_failures) > 20
