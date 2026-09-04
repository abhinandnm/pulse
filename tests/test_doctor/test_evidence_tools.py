import pytest
from pulse.domain.types import Bank, ErrorCode, ActionType, IncidentSeverity
from pulse.domain.incident import IncidentRecord
from pulse.observer.collector import TelemetryObserver
from pulse.simulator.scenarios import PaymentScenarioRunner
from pulse.simulator.failures import FailureScenarioType
from pulse.memory.repository import IncidentRepository
from pulse.doctor.tools import DiagnosticToolkit


class TestDiagnosticToolkit:
    def setup_method(self):
        self.observer = TelemetryObserver(window_seconds=60)
        self.repo = IncidentRepository()
        self.toolkit = DiagnosticToolkit(observer=self.observer, repository=self.repo)

        # Ingest a small simulation run
        runner = PaymentScenarioRunner(seed=42)
        results = runner.run_scenario(
            FailureScenarioType.PSP_TIMEOUT,
            count=30,
            target_route_id="psp_aggregator_fallback",
        )
        self.observer.record_batch(results)

        # Seed 1 historical incident
        inc = IncidentRecord(
            incident_id="inc_hist_01",
            severity=IncidentSeverity.HIGH,
            trigger_metric="timeout_rate > 0.05",
            root_cause="PSP Aggregator connection timeouts",
            actions_taken=[ActionType.SPLIT_TRAFFIC_CANARY],
            revenue_at_risk_inr=15000.0,
            recovered_revenue_inr=14000.0,
        )
        self.repo.save_incident(inc)

    def test_get_route_health(self):
        health = self.toolkit.get_route_health("psp_aggregator_fallback")
        assert health["route_id"] == "psp_aggregator_fallback"
        assert "success_rate" in health
        assert "timeout_rate" in health
        assert "baseline_expected_sr" in health
        assert health["total_transactions"] == 30

    def test_get_recent_metrics(self):
        metrics = self.toolkit.get_recent_metrics()
        assert metrics["total_transactions"] == 30
        assert "latency" in metrics
        assert "p95_ms" in metrics["latency"]
        assert "predictive_health" in metrics
        assert "wilson_ci" in metrics

    def test_get_baseline_metrics(self):
        sys_b = self.toolkit.get_baseline_metrics("SYSTEM")
        assert sys_b["expected_success_rate"] == 0.985

        route_b = self.toolkit.get_baseline_metrics("psp_hdfc_direct")
        assert route_b["expected_success_rate"] == 0.990

    def test_get_error_distribution(self):
        dist = self.toolkit.get_error_distribution()
        assert ErrorCode.PSP_TIMEOUT.value in dist
        assert dist[ErrorCode.PSP_TIMEOUT.value] > 0

    def test_get_bank_metrics(self):
        b_metrics = self.toolkit.get_bank_metrics()
        assert len(b_metrics) > 0
        for b_name, data in b_metrics.items():
            assert "observed_success_rate" in data
            assert "baseline_expected_sr" in data

    def test_get_similar_historical_incidents(self):
        past = self.toolkit.get_similar_historical_incidents(query="timeout_rate > 0.05")
        assert len(past) >= 1
        assert past[0]["incident_id"] == "inc_hist_01"
        assert past[0]["similarity_score"] > 0.30
