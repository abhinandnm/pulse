from typing import Dict, Any, List, Optional
from pulse.domain.telemetry import TelemetrySnapshot
from pulse.domain.types import Bank
from pulse.observer.collector import TelemetryObserver
from pulse.observer.baseline import BaselineManager
from pulse.memory.repository import IncidentRepository
from pulse.memory.retriever import IncidentRetriever


class DiagnosticToolkit:
    """
    Structured query tools provided to the Grounded AI Doctor.
    Ensures all AI hypotheses are strictly grounded in factual telemetry,
    preventing hallucinations.
    """

    def __init__(
        self,
        observer: TelemetryObserver,
        baseline_manager: Optional[BaselineManager] = None,
        repository: Optional[IncidentRepository] = None,
    ):
        self.observer = observer
        self.baseline_manager = baseline_manager or observer.baseline_manager
        self.repository = repository or IncidentRepository()
        self.retriever = IncidentRetriever(self.repository)

    def get_route_health(self, route_id: str) -> Dict[str, Any]:
        """Query real-time health and performance metrics for a specific route."""
        snapshot = self.observer.get_snapshot()
        health = snapshot.route_health.get(route_id)
        baseline = self.baseline_manager.get_route_baseline(route_id)

        if not health:
            return {
                "route_id": route_id,
                "status": "UNKNOWN",
                "message": f"No telemetry available for route '{route_id}' in current window.",
            }

        return {
            "route_id": route_id,
            "status": health.status.value,
            "success_rate": health.success_rate,
            "error_rate": health.error_rate,
            "timeout_rate": health.timeout_rate,
            "p95_latency_ms": health.p95_latency_ms,
            "total_transactions": health.total_transactions,
            "failed_transactions": health.failed_transactions,
            "is_quarantined": health.is_quarantined,
            "baseline_expected_sr": baseline.expected_success_rate,
            "baseline_expected_p95_ms": baseline.expected_p95_latency_ms,
        }

    def get_recent_metrics(self) -> Dict[str, Any]:
        """Fetch the latest windowed operational telemetry snapshot."""
        snapshot = self.observer.get_snapshot()
        return {
            "window_seconds": snapshot.window_seconds,
            "total_transactions": snapshot.total_transactions,
            "successful_transactions": snapshot.successful_transactions,
            "failed_transactions": snapshot.failed_transactions,
            "success_rate": snapshot.success_rate,
            "error_rate": snapshot.error_rate,
            "timeout_rate": snapshot.timeout_rate,
            "latency": {
                "p50_ms": snapshot.latency.p50_ms,
                "p90_ms": snapshot.latency.p90_ms,
                "p95_ms": snapshot.latency.p95_ms,
                "p99_ms": snapshot.latency.p99_ms,
                "mean_ms": snapshot.latency.mean_ms,
            },
            "predictive_health": snapshot.predictive_health.value,
            "wilson_ci": {
                "lower": snapshot.success_rate_ci.lower if snapshot.success_rate_ci else None,
                "upper": snapshot.success_rate_ci.upper if snapshot.success_rate_ci else None,
            },
        }

    def get_baseline_metrics(self, target_id: str = "SYSTEM") -> Dict[str, Any]:
        """Retrieve established baseline metrics for the system or a specific route."""
        if target_id == "SYSTEM":
            base = self.baseline_manager.get_system_baseline()
        else:
            base = self.baseline_manager.get_route_baseline(target_id)

        return {
            "target_id": base.target_id,
            "expected_success_rate": base.expected_success_rate,
            "expected_p95_latency_ms": base.expected_p95_latency_ms,
            "expected_timeout_rate": base.expected_timeout_rate,
            "expected_tpm": base.expected_tpm,
        }

    def get_error_distribution(self) -> Dict[str, int]:
        """Return the count of errors grouped by ErrorCode in the current window."""
        snapshot = self.observer.get_snapshot()
        return dict(snapshot.error_distribution)

    def get_bank_metrics(self) -> Dict[str, Any]:
        """Return success rates for each issuer bank."""
        snapshot = self.observer.get_snapshot()
        bank_report = {}
        for bank_name, sr in snapshot.bank_breakdown.items():
            try:
                b_enum = Bank(bank_name)
                expected_sr = self.baseline_manager.get_bank_baseline_sr(b_enum)
            except ValueError:
                expected_sr = 0.98
            bank_report[bank_name] = {
                "observed_success_rate": sr,
                "baseline_expected_sr": expected_sr,
                "delta": round(expected_sr - sr, 4),
            }
        return bank_report

    def get_similar_historical_incidents(
        self,
        query: str,
        target_route: Optional[str] = None,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Search historical incident memory for past occurrences and successful actions."""
        matches = self.retriever.find_similar_incidents(
            trigger_metric=query,
            target_route=target_route,
            top_k=top_k,
        )
        results = []
        for inc, score in matches:
            results.append({
                "incident_id": inc.incident_id,
                "trigger_metric": inc.trigger_metric,
                "root_cause": inc.root_cause,
                "actions_taken": [a.value for a in inc.actions_taken],
                "similarity_score": score,
                "recovered_revenue_inr": inc.recovered_revenue_inr,
            })
        return results
