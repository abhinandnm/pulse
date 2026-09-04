from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from pulse.domain.types import (
    SystemState,
    RouteStatus,
    Bank,
    PaymentMethod,
    ErrorCode,
    ActionType,
    CanaryGateStatus,
    IncidentSeverity,
    PaymentState,
    OperatingMode,
    PredictiveHealth,
    WebhookEventType,
)
from pulse.domain.transaction import Transaction, TransactionResult
from pulse.domain.route import PaymentRoute, RouteHealth
from pulse.domain.telemetry import ConfidenceInterval, LatencyMetrics, TelemetrySnapshot
from pulse.domain.incident import DiagnosticEvidence, DiagnosticHypothesis, IncidentRecord
from pulse.domain.counterfactual import CandidateEvaluation, CounterfactualDecision
from pulse.domain.canary import CanaryGate, CanaryConfig, CanaryState
from pulse.domain.events import StateTransitionEvent, AuditEvent


class TestTypesAndEnums:
    def test_enums_are_string_compatible(self):
        assert SystemState.HEALTHY == "HEALTHY"
        assert RouteStatus.ACTIVE == "ACTIVE"
        assert Bank.HDFC == "HDFC"
        assert PaymentMethod.UPI == "UPI"
        assert ErrorCode.PSP_TIMEOUT == "PSP_TIMEOUT"
        assert ActionType.SPLIT_TRAFFIC_CANARY == "SPLIT_TRAFFIC_CANARY"
        assert CanaryGateStatus.PASSED == "PASSED"
        assert IncidentSeverity.CRITICAL == "CRITICAL"
        assert PaymentState.CAPTURED == "CAPTURED"
        assert OperatingMode.AUTONOMOUS == "AUTONOMOUS"
        assert PredictiveHealth.DEGRADED == "DEGRADED"
        assert WebhookEventType.PAYMENT_AUTHORIZED == "payment.authorized"

    def test_invalid_enum_raises_error(self):
        with pytest.raises(ValueError):
            Bank("UNKNOWN_BANK")


class TestTransactionContract:
    def test_valid_transaction(self):
        txn = Transaction(
            transaction_id="txn_001",
            amount_inr=500.0,
            bank=Bank.HDFC,
            payment_method=PaymentMethod.UPI,
            route_id="psp_hdfc_direct",
        )
        assert txn.transaction_id == "txn_001"
        assert txn.amount_inr == 500.0
        assert txn.idempotency_key.startswith("idemp_")
        assert txn.payment_state == PaymentState.CREATED
        assert txn.retry_count == 0
        assert txn.is_synthetic is False

    def test_amount_must_be_positive(self):
        with pytest.raises(ValidationError):
            Transaction(
                transaction_id="txn_neg",
                amount_inr=-10.0,
                bank=Bank.SBI,
                payment_method=PaymentMethod.CARD,
                route_id="psp_hdfc_direct",
            )

    def test_zero_amount_forbidden(self):
        with pytest.raises(ValidationError):
            Transaction(
                transaction_id="txn_zero",
                amount_inr=0.0,
                bank=Bank.SBI,
                payment_method=PaymentMethod.CARD,
                route_id="psp_hdfc_direct",
            )

    def test_transaction_is_frozen(self):
        txn = Transaction(
            transaction_id="txn_frozen",
            amount_inr=100.0,
            bank=Bank.ICICI,
            payment_method=PaymentMethod.NET_BANKING,
            route_id="psp_hdfc_direct",
        )
        with pytest.raises(ValidationError):
            txn.amount_inr = 200.0


class TestTransactionResultContract:
    def test_success_result_auto_captured(self):
        txn = Transaction(
            transaction_id="txn_success",
            amount_inr=250.0,
            bank=Bank.AXIS,
            payment_method=PaymentMethod.UPI,
            route_id="psp_hdfc_direct",
        )
        result = TransactionResult(
            transaction=txn,
            success=True,
            latency_ms=120.5,
            psp_reference="ref_12345",
        )
        assert result.success is True
        assert result.payment_state == PaymentState.CAPTURED
        assert result.error_code == ErrorCode.NONE

    def test_timeout_result_auto_unknown(self):
        txn = Transaction(
            transaction_id="txn_timeout",
            amount_inr=250.0,
            bank=Bank.AXIS,
            payment_method=PaymentMethod.UPI,
            route_id="psp_hdfc_direct",
        )
        result = TransactionResult(
            transaction=txn,
            success=False,
            latency_ms=4500.0,
            error_code=ErrorCode.PSP_TIMEOUT,
            error_message="Gateway read timeout",
        )
        assert result.success is False
        assert result.payment_state == PaymentState.UNKNOWN

    def test_failure_result_auto_failed(self):
        txn = Transaction(
            transaction_id="txn_fail",
            amount_inr=250.0,
            bank=Bank.AXIS,
            payment_method=PaymentMethod.UPI,
            route_id="psp_hdfc_direct",
        )
        result = TransactionResult(
            transaction=txn,
            success=False,
            latency_ms=80.0,
            error_code=ErrorCode.GATEWAY_ERROR,
        )
        assert result.success is False
        assert result.payment_state == PaymentState.FAILED


class TestRouteContract:
    def test_payment_route_creation(self):
        route = PaymentRoute(
            route_id="psp_hdfc_direct",
            name="HDFC Direct Switch",
            supported_methods=[PaymentMethod.UPI, PaymentMethod.NET_BANKING],
            supported_banks=[Bank.HDFC],
            cost_per_txn_inr=0.25,
        )
        assert route.route_id == "psp_hdfc_direct"
        assert Bank.HDFC in route.supported_banks
        assert PaymentMethod.CARD not in route.supported_methods

    def test_route_health_bounds(self):
        health = RouteHealth(
            route_id="psp_hdfc_direct",
            status=RouteStatus.ACTIVE,
            success_rate=0.98,
            error_rate=0.02,
            timeout_rate=0.01,
            p95_latency_ms=180.0,
            total_transactions=100,
            failed_transactions=2,
        )
        assert health.success_rate == 0.98
        assert health.is_quarantined is False

        with pytest.raises(ValidationError):
            RouteHealth(route_id="psp_invalid", success_rate=1.5)


class TestTelemetryContract:
    def test_confidence_interval_bounds(self):
        ci = ConfidenceInterval(lower=0.92, upper=0.98, confidence_level=0.95)
        assert ci.lower == 0.92
        assert ci.upper == 0.98

        with pytest.raises(ValidationError):
            ConfidenceInterval(lower=-0.1, upper=1.0)

    def test_telemetry_snapshot(self):
        latency = LatencyMetrics(p50_ms=100.0, p90_ms=180.0, p95_ms=220.0, p99_ms=450.0, mean_ms=120.0)
        snap = TelemetrySnapshot(
            total_transactions=100,
            successful_transactions=95,
            failed_transactions=5,
            success_rate=0.95,
            error_rate=0.05,
            timeout_rate=0.02,
            latency=latency,
            predictive_health=PredictiveHealth.HEALTHY,
        )
        assert snap.total_transactions == 100
        assert snap.latency.p95_ms == 220.0
        assert snap.predictive_health == PredictiveHealth.HEALTHY


class TestIncidentContract:
    def test_incident_and_evidence(self):
        evidence = DiagnosticEvidence(
            metric_name="timeout_rate",
            observed_value=0.25,
            threshold_value=0.05,
            description="Timeout spike detected on PSP_A",
        )
        hyp = DiagnosticHypothesis(
            title="PSP A Network Outage",
            description="Upstream connection reset causing 25% timeouts",
            confidence_score=0.92,
            supporting_evidence=[evidence],
            recommended_action=ActionType.SWITCH_ROUTE,
            target_route_id="psp_backup",
        )
        inc = IncidentRecord(
            trigger_metric="timeout_rate > 0.05",
            root_cause="PSP_A downstream degradation",
            severity=IncidentSeverity.HIGH,
            hypotheses=[hyp],
            actions_taken=[ActionType.SWITCH_ROUTE],
            revenue_at_risk_inr=50000.0,
            recovered_revenue_inr=48000.0,
        )
        assert inc.severity == IncidentSeverity.HIGH
        assert len(inc.hypotheses) == 1
        assert inc.hypotheses[0].confidence_score == 0.92
        assert inc.recovered_revenue_inr == 48000.0


class TestCounterfactualContract:
    def test_counterfactual_decision(self):
        cand1 = CandidateEvaluation(
            action=ActionType.NO_ACTION,
            expected_sr_lift=0.0,
            risk_score=0.9,
            utility_score=10.0,
            rationale="Do nothing, risk high revenue loss",
        )
        cand2 = CandidateEvaluation(
            action=ActionType.SPLIT_TRAFFIC_CANARY,
            target_route_id="psp_backup",
            expected_sr_lift=0.20,
            risk_score=0.1,
            utility_score=85.0,
            rationale="Canary 20% to backup route",
        )
        decision = CounterfactualDecision(
            evaluated_candidates=[cand1, cand2],
            chosen_action=ActionType.SPLIT_TRAFFIC_CANARY,
            chosen_route_id="psp_backup",
            projected_revenue_recovery_inr=45000.0,
            explanation="Canary testing minimizes blast radius while recovering 20% SR lift",
        )
        assert decision.chosen_action == ActionType.SPLIT_TRAFFIC_CANARY
        assert len(decision.evaluated_candidates) == 2


class TestCanaryContract:
    def test_canary_config_and_gates(self):
        gate = CanaryGate(
            gate_name="LATENCY_SLO",
            status=CanaryGateStatus.PASSED,
            threshold=500.0,
            observed_value=210.0,
            passed=True,
            message="p95 latency is within SLO",
        )
        config = CanaryConfig(
            target_route_id="psp_backup",
            traffic_stages=[20, 50, 100],
            min_sample_size=30,
        )
        state = CanaryState(
            target_route_id="psp_backup",
            fallback_route_id="psp_primary",
            current_traffic_percentage=20,
            gates=[gate],
        )
        assert state.current_traffic_percentage == 20
        assert config.traffic_stages == [20, 50, 100]
        assert state.gates[0].passed is True


class TestEventsContract:
    def test_state_transition_and_audit(self):
        trans = StateTransitionEvent(
            from_state=SystemState.HEALTHY,
            to_state=SystemState.DEGRADED,
            reason="Success rate dropped below 0.85 threshold",
            trigger="STATISTICAL_OBSERVER",
        )
        audit = AuditEvent(
            actor="AI_DOCTOR",
            action=ActionType.SWITCH_ROUTE,
            description="Recommended route switch from psp_primary to psp_backup",
            details={"confidence": 0.94},
        )
        assert trans.from_state == SystemState.HEALTHY
        assert trans.to_state == SystemState.DEGRADED
        assert audit.actor == "AI_DOCTOR"
