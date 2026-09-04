import pytest
from datetime import datetime, timezone
from pulse.domain.types import Bank, ErrorCode, IncidentSeverity, PredictiveHealth
from pulse.domain.telemetry import TelemetrySnapshot, LatencyMetrics, ConfidenceInterval
from pulse.domain.route import RouteHealth, RouteStatus
from pulse.observer.anomaly import StatisticalAnomalyDetector, AnomalyReport


def build_mock_snapshot(
    total: int = 50,
    success_rate: float = 0.98,
    timeout_rate: float = 0.01,
    p95_latency_ms: float = 140.0,
    bank_breakdown: dict = None,
    route_health: dict = None,
) -> TelemetrySnapshot:
    succ = int(total * success_rate)
    fail = total - succ
    return TelemetrySnapshot(
        total_transactions=total,
        successful_transactions=succ,
        failed_transactions=fail,
        success_rate=success_rate,
        error_rate=round(1.0 - success_rate, 4),
        timeout_rate=timeout_rate,
        latency=LatencyMetrics(p95_ms=p95_latency_ms),
        success_rate_ci=ConfidenceInterval(lower=success_rate - 0.03, upper=min(1.0, success_rate + 0.02)),
        bank_breakdown=bank_breakdown or {"HDFC": success_rate, "ICICI": success_rate},
        route_health=route_health or {},
        predictive_health=PredictiveHealth.HEALTHY,
    )


class TestStatisticalAnomalyDetector:
    def setup_method(self):
        self.detector = StatisticalAnomalyDetector(min_sample_size=15)

    def test_insufficient_sample_size_ignored(self):
        snap = build_mock_snapshot(total=10, success_rate=0.50)  # Heavy failure, but only 10 txns
        report = self.detector.evaluate(snap)
        assert report.is_anomaly is False
        assert report.primary_anomaly_type == "INSUFFICIENT_DATA"

    def test_healthy_snapshot_no_anomaly(self):
        snap = build_mock_snapshot(total=100, success_rate=0.985, timeout_rate=0.005, p95_latency_ms=130.0)
        report = self.detector.evaluate(snap)
        assert report.is_anomaly is False
        assert report.severity == IncidentSeverity.LOW
        assert report.predictive_health == PredictiveHealth.HEALTHY

    def test_critical_success_rate_drop(self):
        # Baseline is 98.5%, current is 65% (drop > 25%)
        snap = build_mock_snapshot(total=100, success_rate=0.65)
        report = self.detector.evaluate(snap)
        assert report.is_anomaly is True
        assert report.severity == IncidentSeverity.CRITICAL
        assert report.predictive_health == PredictiveHealth.CRITICAL
        assert any(e.metric_name == "success_rate" for e in report.evidence)

    def test_psp_timeout_spike(self):
        # 25% timeout rate
        snap = build_mock_snapshot(total=80, success_rate=0.75, timeout_rate=0.25)
        report = self.detector.evaluate(snap)
        assert report.is_anomaly is True
        assert report.severity in (IncidentSeverity.HIGH, IncidentSeverity.CRITICAL)
        assert any(e.metric_name == "timeout_rate" for e in report.evidence)

    def test_latency_spike(self):
        # Latency spikes to 3500ms
        snap = build_mock_snapshot(total=60, success_rate=0.95, p95_latency_ms=3500.0)
        report = self.detector.evaluate(snap)
        assert report.is_anomaly is True
        assert report.severity == IncidentSeverity.HIGH
        assert any(e.metric_name == "p95_latency_ms" for e in report.evidence)

    def test_bank_issuer_outage(self):
        # ICICI collapses to 10% SR while HDFC is 98%
        snap = build_mock_snapshot(
            total=100,
            success_rate=0.88,
            bank_breakdown={"HDFC": 0.98, "ICICI": 0.10},
        )
        report = self.detector.evaluate(snap)
        assert report.is_anomaly is True
        assert Bank.ICICI in report.affected_banks
        assert report.primary_anomaly_type == "BANK_ISSUER_OUTAGE"

    def test_affected_route_tracking(self):
        route_h = {
            "psp_hdfc_direct": RouteHealth(
                route_id="psp_hdfc_direct",
                status=RouteStatus.DEGRADED,
                success_rate=0.60,
                error_rate=0.40,
                timeout_rate=0.30,
            )
        }
        snap = build_mock_snapshot(total=50, success_rate=0.70, route_health=route_h)
        report = self.detector.evaluate(snap)
        assert report.is_anomaly is True
        assert "psp_hdfc_direct" in report.affected_route_ids
