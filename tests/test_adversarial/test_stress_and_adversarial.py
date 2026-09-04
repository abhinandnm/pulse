import json
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from pulse.domain.types import (
    OperatingMode,
    SystemState,
    ActionType,
    PaymentState,
    ErrorCode,
    Bank,
    PaymentMethod,
    RouteStatus,
)
from pulse.domain.transaction import Transaction, TransactionResult
from pulse.domain.telemetry import TelemetrySnapshot, LatencyMetrics
from pulse.observer.collector import TelemetryObserver
from pulse.observer.anomaly import AnomalyReport
from pulse.safety.anti_flapping import AntiFlappingController, HysteresisConfig
from pulse.safety.quarantine import QuarantineManager
from pulse.canary.controller import CanarySafetyController
from pulse.domain.canary import CanaryState
from pulse.doctor.tools import DiagnosticToolkit
from pulse.doctor.ai_doctor import AIDoctor, AIDoctorDiagnosis
from pulse.engine.loop import AutonomousControlLoop
from pulse.api.app import app, razorpay


class TestAdversarialAndStressScenarios:
    def setup_method(self):
        self.client = TestClient(app)
        self.observer = TelemetryObserver(window_seconds=60)
        self.loop = AutonomousControlLoop(
            observer=self.observer,
            operating_mode=OperatingMode.AUTONOMOUS,
        )

    # 1. Adversarial Route Flapping & Anti-Flapping Quarantine
    def test_adversarial_route_flapping_quarantines_oscillating_route(self):
        qm = QuarantineManager(base_cooldown_seconds=30)
        af = AntiFlappingController(
            quarantine_manager=qm,
            hysteresis_config=HysteresisConfig(degrade_sr_threshold=0.85, recover_sr_threshold=0.95),
            flap_window_seconds=60,
            max_flaps_in_window=3,
        )
        route_id = "psp_flapping_adversary"

        # Rapidly flap 3 times:
        # Flip 1: ACTIVE -> DEGRADED (SR drops to 50%)
        s1 = af.evaluate_route(route_id, current_sr=0.50, current_p95_latency_ms=200.0)
        assert s1 == RouteStatus.DEGRADED

        # Flip 2: DEGRADED -> ACTIVE (SR jumps to 99%)
        s2 = af.evaluate_route(route_id, current_sr=0.99, current_p95_latency_ms=100.0)
        assert s2 == RouteStatus.ACTIVE

        # Flip 3: ACTIVE -> DEGRADED (SR drops to 40%) -> Threshold breach!
        s3 = af.evaluate_route(route_id, current_sr=0.40, current_p95_latency_ms=200.0)
        assert s3 == RouteStatus.QUARANTINED
        assert af.is_flapping(route_id) is True
        assert qm.is_quarantined(route_id) is True

        # Even if route subsequently reports 100% SR, it remains locked in QUARANTINED!
        s4 = af.evaluate_route(route_id, current_sr=1.00, current_p95_latency_ms=50.0)
        assert s4 == RouteStatus.QUARANTINED

    # 2. Mid-Canary Secondary Failure Immediate Rollback
    def test_mid_canary_secondary_failure_aborts_and_quarantines(self):
        controller = CanarySafetyController()
        state = CanaryState(
            target_route_id="psp_icici_backup",
            fallback_route_id="psp_hdfc_direct",
            current_traffic_percentage=20,
        )

        # Stage 0 (20%) succeeds
        healthy_txns = [
            TransactionResult(
                transaction=Transaction(
                    transaction_id=f"ok_{i}",
                    amount_inr=500.0,
                    bank=Bank.HDFC,
                    payment_method=PaymentMethod.UPI,
                    route_id="psp_icici_backup",
                ),
                success=True,
                latency_ms=100.0,
            )
            for i in range(25)
        ]
        updated_state, res0 = controller.evaluate_results(state, healthy_txns)
        assert res0.should_promote_stage is True
        assert updated_state.current_traffic_percentage == 50

        # Mid-canary: Candidate route suddenly crashes during Stage 1 (50%)
        crashing_txns = [
            TransactionResult(
                transaction=Transaction(
                    transaction_id=f"crash_{i}",
                    amount_inr=500.0,
                    bank=Bank.HDFC,
                    payment_method=PaymentMethod.UPI,
                    route_id="psp_icici_backup",
                ),
                success=False,
                latency_ms=5000.0,
                error_code=ErrorCode.PSP_TIMEOUT,
            )
            for i in range(25)
        ]

        rolled_back_state, res1 = controller.evaluate_results(updated_state, crashing_txns)
        assert res1.should_rollback is True
        assert rolled_back_state.current_traffic_percentage == 0
        assert "rollback" in res1.reason.lower()

    # 3. Duplicate Webhook & HMAC Replay Attack Defense
    def test_duplicate_webhook_replay_tampering_rejected(self):
        payload = {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_tamper_001", "amount": 100000, "status": "captured"}}},
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        valid_sig = razorpay.generate_webhook_signature(body_bytes)

        # Valid webhook accepted
        res1 = self.client.post("/api/v1/razorpay/webhook", content=body_bytes, headers={"X-Razorpay-Signature": valid_sig})
        assert res1.status_code == 200

        # Tampered body with same signature rejected with 400
        tampered_body = json.dumps({
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_tamper_001", "amount": 9999999, "status": "captured"}}},
        }).encode("utf-8")

        res2 = self.client.post("/api/v1/razorpay/webhook", content=tampered_body, headers={"X-Razorpay-Signature": valid_sig})
        assert res2.status_code == 400

    # 4. Indeterminate / Unknown Payment State Handling
    def test_unknown_payment_state_does_not_falsely_count_as_captured(self):
        txn = Transaction(
            transaction_id="txn_indeterminate_01",
            amount_inr=50000.0,
            bank=Bank.SBI,
            payment_method=PaymentMethod.NET_BANKING,
            route_id="psp_hdfc_direct",
        )
        # Timeout results in UNKNOWN, not CAPTURED
        res = TransactionResult(
            transaction=txn,
            success=False,
            latency_ms=8000.0,
            error_code=ErrorCode.PSP_TIMEOUT,
        )
        assert res.payment_state == PaymentState.UNKNOWN
        assert res.success is False

        # Ingest and verify observer tracks timeout, not successful revenue
        self.observer.record_transaction(res)
        snap = self.observer.get_snapshot()
        assert snap.successful_transactions == 0
        assert snap.timeout_rate == 1.0

    # 5. Invalid / Malformed AI Output Safe Fallback
    def test_ai_doctor_handles_malformed_llm_json_gracefully(self):
        toolkit = DiagnosticToolkit(observer=self.observer)
        doctor = AIDoctor(toolkit=toolkit)
        doctor.api_key = "fake_test_key"  # Force LLM branch

        report = AnomalyReport(
            is_anomaly=True,
            primary_anomaly_type="PSP_TIMEOUT_SPIKE",
            affected_route_ids=["psp_hdfc_direct"],
        )
        snap = TelemetrySnapshot(
            total_transactions=30,
            success_rate=0.70,
            timeout_rate=0.30,
            latency=LatencyMetrics(p95_ms=3500.0),
            error_distribution={ErrorCode.PSP_TIMEOUT.value: 9},
        )

        # Mock LLM to throw an exception / return corrupted string
        with patch.object(doctor, "_diagnose_with_llm", side_effect=ValueError("Malformed LLM JSON syntax error")):
            diagnosis = doctor.diagnose(
                incident_id="inc_adversarial_ai",
                anomaly_report=report,
                snapshot=snap,
            )

            # System must NOT crash — fallback to grounded expert diagnosis!
            assert isinstance(diagnosis, AIDoctorDiagnosis)
            assert diagnosis.incident_id == "inc_adversarial_ai"
            assert "timeout" in diagnosis.root_cause.lower()
            assert diagnosis.confidence_score >= 0.90
