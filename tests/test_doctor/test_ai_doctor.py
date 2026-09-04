import pytest
from pulse.domain.types import ActionType, Bank, ErrorCode, IncidentSeverity, PredictiveHealth
from pulse.domain.telemetry import TelemetrySnapshot, LatencyMetrics
from pulse.domain.incident import DiagnosticEvidence, IncidentRecord
from pulse.observer.collector import TelemetryObserver
from pulse.observer.anomaly import AnomalyReport
from pulse.memory.repository import IncidentRepository
from pulse.doctor.tools import DiagnosticToolkit
from pulse.doctor.ai_doctor import AIDoctor, AIDoctorDiagnosis


class TestAIDoctor:
    def setup_method(self):
        self.observer = TelemetryObserver(window_seconds=60)
        self.repo = IncidentRepository()
        self.toolkit = DiagnosticToolkit(observer=self.observer, repository=self.repo)
        self.doctor = AIDoctor(toolkit=self.toolkit)

        # Seed 1 historical precedent
        self.repo.save_incident(
            IncidentRecord(
                incident_id="inc_past_timeout",
                severity=IncidentSeverity.HIGH,
                trigger_metric="timeout_rate > 0.05",
                root_cause="PSP timeout spike on psp_hdfc_direct",
                actions_taken=[ActionType.SPLIT_TRAFFIC_CANARY],
                revenue_at_risk_inr=10000.0,
                recovered_revenue_inr=9500.0,
            )
        )

    def test_diagnose_timeout_spike_with_precedent(self):
        evi = DiagnosticEvidence(
            metric_name="timeout_rate",
            observed_value=0.25,
            threshold_value=0.05,
            description="Timeout rate spiked to 25%",
        )
        report = AnomalyReport(
            is_anomaly=True,
            severity=IncidentSeverity.HIGH,
            predictive_health=PredictiveHealth.DEGRADED,
            primary_anomaly_type="PSP_TIMEOUT_SPIKE",
            affected_route_ids=["psp_hdfc_direct"],
            evidence=[evi],
        )
        snap = TelemetrySnapshot(
            total_transactions=50,
            success_rate=0.75,
            timeout_rate=0.25,
            latency=LatencyMetrics(p95_ms=3800.0),
            error_distribution={ErrorCode.PSP_TIMEOUT.value: 12},
        )

        diagnosis = self.doctor.diagnose(
            incident_id="inc_test_01",
            anomaly_report=report,
            snapshot=snap,
        )

        assert isinstance(diagnosis, AIDoctorDiagnosis)
        assert diagnosis.incident_id == "inc_test_01"
        assert "timeout" in diagnosis.root_cause.lower()
        assert diagnosis.confidence_score >= 0.90
        assert diagnosis.recommended_action in (ActionType.SPLIT_TRAFFIC_CANARY, ActionType.SWITCH_ROUTE)
        assert diagnosis.target_route_id is not None
        assert len(diagnosis.evidence) > 0
        assert diagnosis.historical_precedent is not None
        assert "inc_past_timeout" in diagnosis.historical_precedent

    def test_diagnose_bank_issuer_outage(self):
        evi = DiagnosticEvidence(
            metric_name="bank_ICICI_success_rate",
            observed_value=0.10,
            threshold_value=0.985,
            description="ICICI CBS down",
        )
        report = AnomalyReport(
            is_anomaly=True,
            severity=IncidentSeverity.HIGH,
            primary_anomaly_type="BANK_ISSUER_OUTAGE",
            affected_banks=[Bank.ICICI],
            evidence=[evi],
        )
        snap = TelemetrySnapshot(
            total_transactions=50,
            success_rate=0.85,
            bank_breakdown={"ICICI": 0.10, "HDFC": 0.98},
        )

        diagnosis = self.doctor.diagnose(
            incident_id="inc_bank_01",
            anomaly_report=report,
            snapshot=snap,
        )

        assert "ICICI" in diagnosis.root_cause or "Core Banking" in diagnosis.root_cause
        assert diagnosis.confidence_score >= 0.85

    def test_diagnose_gateway_error_recommends_quarantine(self):
        evi = DiagnosticEvidence(
            metric_name="error_rate",
            observed_value=0.50,
            threshold_value=0.02,
            description="HTTP 500 spike",
        )
        report = AnomalyReport(
            is_anomaly=True,
            severity=IncidentSeverity.CRITICAL,
            primary_anomaly_type="GATEWAY_ERROR",
            affected_route_ids=["psp_hdfc_direct"],
            evidence=[evi],
        )
        snap = TelemetrySnapshot(
            total_transactions=50,
            success_rate=0.50,
            error_rate=0.50,
            error_distribution={ErrorCode.GATEWAY_ERROR.value: 25},
        )

        diagnosis = self.doctor.diagnose(
            incident_id="inc_gw_01",
            anomaly_report=report,
            snapshot=snap,
        )

        assert diagnosis.recommended_action == ActionType.QUARANTINE_ROUTE
        assert diagnosis.confidence_score >= 0.90
