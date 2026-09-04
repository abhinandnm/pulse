from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import IncidentSeverity, PredictiveHealth, Bank
from pulse.domain.telemetry import TelemetrySnapshot
from pulse.domain.incident import DiagnosticEvidence
from pulse.observer.baseline import BaselineManager, BaselineProfile


class AnomalyReport(BaseModel):
    """Structured report produced by the Statistical Anomaly Detector."""
    model_config = ConfigDict(frozen=True)

    is_anomaly: bool = False
    severity: IncidentSeverity = IncidentSeverity.LOW
    predictive_health: PredictiveHealth = PredictiveHealth.HEALTHY
    primary_anomaly_type: str = "NONE"
    affected_route_ids: List[str] = Field(default_factory=list)
    affected_banks: List[Bank] = Field(default_factory=list)
    evidence: List[DiagnosticEvidence] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatisticalAnomalyDetector:
    """
    Deterministic anomaly detector utilizing statistical thresholds,
    Wilson confidence lower bounds, and baseline comparisons.
    """

    def __init__(
        self,
        baseline_manager: Optional[BaselineManager] = None,
        min_sample_size: int = 15,
        sr_drop_critical_threshold: float = 0.25,
        sr_drop_high_threshold: float = 0.10,
        sr_drop_medium_threshold: float = 0.05,
        timeout_threshold: float = 0.05,
        latency_multiplier_threshold: float = 2.0,
    ):
        self.baseline_manager = baseline_manager or BaselineManager()
        self.min_sample_size = min_sample_size
        self.sr_drop_critical = sr_drop_critical_threshold
        self.sr_drop_high = sr_drop_high_threshold
        self.sr_drop_medium = sr_drop_medium_threshold
        self.timeout_threshold = timeout_threshold
        self.latency_multiplier = latency_multiplier_threshold

    def evaluate(self, snapshot: TelemetrySnapshot) -> AnomalyReport:
        """Evaluate a telemetry snapshot for statistically significant anomalies."""
        now = datetime.now(timezone.utc)

        # Insufficient sample size -> cannot declare statistical anomaly with confidence
        if snapshot.total_transactions < self.min_sample_size:
            return AnomalyReport(
                is_anomaly=False,
                severity=IncidentSeverity.LOW,
                predictive_health=PredictiveHealth.HEALTHY,
                primary_anomaly_type="INSUFFICIENT_DATA",
                timestamp=now,
            )

        system_baseline = self.baseline_manager.get_system_baseline()
        evidence_list: List[DiagnosticEvidence] = []
        affected_routes: List[str] = []
        affected_banks: List[Bank] = []
        primary_type = "NONE"
        highest_severity = IncidentSeverity.LOW

        # 1. Check System Success Rate Degradation
        sr_delta = system_baseline.expected_success_rate - snapshot.success_rate
        if sr_delta >= self.sr_drop_medium:
            if sr_delta >= self.sr_drop_critical:
                sev = IncidentSeverity.CRITICAL
            elif sr_delta >= self.sr_drop_high:
                sev = IncidentSeverity.HIGH
            else:
                sev = IncidentSeverity.MEDIUM

            if self._severity_weight(sev) > self._severity_weight(highest_severity):
                highest_severity = sev
                primary_type = "SUCCESS_RATE_DEGRADATION"

            evidence_list.append(
                DiagnosticEvidence(
                    metric_name="success_rate",
                    observed_value=snapshot.success_rate,
                    threshold_value=system_baseline.expected_success_rate,
                    description=f"System success rate dropped by {round(sr_delta * 100, 1)}% below baseline",
                    timestamp=now,
                )
            )

        # 2. Check Wilson Lower Bound (prevents false alerts on small dips, catches deep drops)
        if snapshot.success_rate_ci and snapshot.success_rate_ci.upper < (system_baseline.expected_success_rate - 0.05):
            evidence_list.append(
                DiagnosticEvidence(
                    metric_name="wilson_upper_bound",
                    observed_value=snapshot.success_rate_ci.upper,
                    threshold_value=system_baseline.expected_success_rate - 0.05,
                    description=f"Wilson 95% upper bound ({snapshot.success_rate_ci.upper}) is strictly below baseline threshold",
                    timestamp=now,
                )
            )

        # 3. Check Timeout Rate Spike
        if snapshot.timeout_rate > self.timeout_threshold:
            sev = IncidentSeverity.HIGH if snapshot.timeout_rate > 0.15 else IncidentSeverity.MEDIUM
            if self._severity_weight(sev) > self._severity_weight(highest_severity):
                highest_severity = sev
                primary_type = "PSP_TIMEOUT_SPIKE"

            evidence_list.append(
                DiagnosticEvidence(
                    metric_name="timeout_rate",
                    observed_value=snapshot.timeout_rate,
                    threshold_value=self.timeout_threshold,
                    description=f"Gateway timeout rate ({round(snapshot.timeout_rate * 100, 1)}%) breached threshold ({round(self.timeout_threshold * 100, 1)}%)",
                    timestamp=now,
                )
            )

        # 4. Check Latency Anomaly
        max_tolerable_latency = system_baseline.expected_p95_latency_ms * self.latency_multiplier
        if snapshot.latency.p95_ms > max_tolerable_latency and snapshot.latency.p95_ms > 800.0:
            sev = IncidentSeverity.HIGH if snapshot.latency.p95_ms > 3000.0 else IncidentSeverity.MEDIUM
            if self._severity_weight(sev) > self._severity_weight(highest_severity):
                highest_severity = sev
                primary_type = "LATENCY_SPIKE"

            evidence_list.append(
                DiagnosticEvidence(
                    metric_name="p95_latency_ms",
                    observed_value=snapshot.latency.p95_ms,
                    threshold_value=max_tolerable_latency,
                    description=f"p95 response latency ({snapshot.latency.p95_ms}ms) exceeded 2x baseline ({max_tolerable_latency}ms)",
                    timestamp=now,
                )
            )

        # 5. Check Per-Route Health & Anomalies
        for r_id, r_health in snapshot.route_health.items():
            r_baseline = self.baseline_manager.get_route_baseline(r_id)
            if (r_baseline.expected_success_rate - r_health.success_rate) >= self.sr_drop_medium or r_health.timeout_rate > self.timeout_threshold:
                affected_routes.append(r_id)
                evidence_list.append(
                    DiagnosticEvidence(
                        metric_name=f"route_{r_id}_success_rate",
                        observed_value=r_health.success_rate,
                        threshold_value=r_baseline.expected_success_rate,
                        description=f"Route {r_id} success rate degraded to {r_health.success_rate}",
                        timestamp=now,
                    )
                )

        # 6. Check Per-Bank Health & Issuer Outages
        for b_str, b_sr in snapshot.bank_breakdown.items():
            try:
                b_enum = Bank(b_str)
                b_baseline = self.baseline_manager.get_bank_baseline_sr(b_enum)
                if (b_baseline - b_sr) >= 0.20:  # 20% drop on specific bank indicates issuer down
                    affected_banks.append(b_enum)
                    if self._severity_weight(IncidentSeverity.HIGH) >= self._severity_weight(highest_severity):
                        highest_severity = IncidentSeverity.HIGH
                        primary_type = "BANK_ISSUER_OUTAGE"

                    evidence_list.append(
                        DiagnosticEvidence(
                            metric_name=f"bank_{b_str}_success_rate",
                            observed_value=b_sr,
                            threshold_value=b_baseline,
                            description=f"Issuer bank {b_str} success rate collapsed to {round(b_sr * 100, 1)}%",
                            timestamp=now,
                        )
                    )
            except ValueError:
                pass

        is_anomaly = len(evidence_list) > 0 and highest_severity != IncidentSeverity.LOW

        # Map to predictive health
        if highest_severity == IncidentSeverity.CRITICAL:
            pred_health = PredictiveHealth.CRITICAL
        elif highest_severity in (IncidentSeverity.HIGH, IncidentSeverity.MEDIUM):
            pred_health = PredictiveHealth.DEGRADED
        else:
            pred_health = PredictiveHealth.HEALTHY

        return AnomalyReport(
            is_anomaly=is_anomaly,
            severity=highest_severity if is_anomaly else IncidentSeverity.LOW,
            predictive_health=pred_health,
            primary_anomaly_type=primary_type if is_anomaly else "NONE",
            affected_route_ids=affected_routes,
            affected_banks=affected_banks,
            evidence=evidence_list,
            timestamp=now,
        )

    @staticmethod
    def _severity_weight(severity: IncidentSeverity) -> int:
        weights = {
            IncidentSeverity.LOW: 1,
            IncidentSeverity.MEDIUM: 2,
            IncidentSeverity.HIGH: 3,
            IncidentSeverity.CRITICAL: 4,
        }
        return weights.get(severity, 0)
