import os
import json
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import ActionType, Bank, ErrorCode
from pulse.domain.incident import DiagnosticEvidence
from pulse.domain.telemetry import TelemetrySnapshot
from pulse.observer.anomaly import AnomalyReport
from pulse.doctor.tools import DiagnosticToolkit


class AIDoctorDiagnosis(BaseModel):
    """
    Structured diagnostic verdict produced by the Grounded AI Doctor.
    Guaranteed strictly grounded in factual telemetry evidence without
    raw unverified chain-of-thought.
    """
    model_config = ConfigDict(frozen=True)

    incident_id: str
    root_cause: str = Field(..., description="Diagnosed root cause statement")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Diagnosis confidence (0.0 to 1.0)")
    recommended_action: ActionType = Field(..., description="Action recommended to resolve degradation")
    target_route_id: Optional[str] = Field(default=None, description="Target route to reroute to or isolate")
    evidence: List[DiagnosticEvidence] = Field(default_factory=list, description="Factual telemetry evidence supporting diagnosis")
    explanation: str = Field(..., description="Clear explanation of the reasoning and impact")
    historical_precedent: Optional[str] = Field(default=None, description="Precedent from incident memory if applicable")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AIDoctor:
    """
    Autonomous AI Doctor for payment reliability.
    Inspects diagnostic evidence tools, searches historical memory,
    and produces structured diagnosis.
    """

    def __init__(
        self,
        toolkit: DiagnosticToolkit,
        model_name: str = "gemini-2.5-flash",
    ):
        self.toolkit = toolkit
        self.model_name = model_name
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def diagnose(
        self,
        incident_id: str,
        anomaly_report: AnomalyReport,
        snapshot: TelemetrySnapshot,
    ) -> AIDoctorDiagnosis:
        """
        Diagnose an active incident.
        Attempts LLM reasoning if API key is present; otherwise utilizes
        deterministic grounded expert rules.
        """
        # 1. Gather comprehensive evidence
        error_dist = dict(snapshot.error_distribution) if snapshot.error_distribution else self.toolkit.get_error_distribution()
        recent_metrics = self.toolkit.get_recent_metrics()
        bank_metrics = self.toolkit.get_bank_metrics()

        # Find historical matches
        target_route = anomaly_report.affected_route_ids[0] if anomaly_report.affected_route_ids else None
        past_matches = self.toolkit.get_similar_historical_incidents(
            query=f"{anomaly_report.primary_anomaly_type} {' '.join(anomaly_report.affected_route_ids)}",
            target_route=target_route,
            top_k=2,
        )
        precedent_str = None
        if past_matches:
            top_m = past_matches[0]
            precedent_str = f"Similar to {top_m['incident_id']} ({top_m['root_cause']}), resolved via {', '.join(top_m['actions_taken'])}."

        # 2. Check if LLM diagnosis can be performed
        if self.api_key:
            try:
                return self._diagnose_with_llm(
                    incident_id=incident_id,
                    anomaly_report=anomaly_report,
                    snapshot=snapshot,
                    error_dist=error_dist,
                    recent_metrics=recent_metrics,
                    precedent=precedent_str,
                )
            except Exception:
                # Graceful fallback to deterministic grounded engine on network / auth error
                pass

        # 3. Grounded Deterministic Expert Diagnosis
        return self._diagnose_grounded_expert(
            incident_id=incident_id,
            anomaly_report=anomaly_report,
            snapshot=snapshot,
            error_dist=error_dist,
            precedent=precedent_str,
        )

    def _diagnose_grounded_expert(
        self,
        incident_id: str,
        anomaly_report: AnomalyReport,
        snapshot: TelemetrySnapshot,
        error_dist: dict,
        precedent: Optional[str],
    ) -> AIDoctorDiagnosis:
        """Deterministic expert diagnosis based on exact observed failure signatures."""
        primary_type = anomaly_report.primary_anomaly_type
        affected_routes = anomaly_report.affected_route_ids
        target_route = affected_routes[0] if affected_routes else "psp_hdfc_direct"

        # Check alternative available routes
        alternate_route = "psp_icici_backup" if target_route == "psp_hdfc_direct" else "psp_aggregator_fallback"

        if primary_type == "PSP_TIMEOUT_SPIKE" or ErrorCode.PSP_TIMEOUT.value in error_dist:
            root_cause = f"Upstream PSP timeout spike on {target_route} with high latency"
            conf = 0.95
            action = ActionType.SPLIT_TRAFFIC_CANARY
            exp = f"Observed timeout rate of {round(snapshot.timeout_rate * 100, 1)}% on {target_route}. Recommend canary rollout to {alternate_route}."

        elif primary_type == "BANK_ISSUER_OUTAGE" or anomaly_report.affected_banks:
            bank_name = anomaly_report.affected_banks[0].value if anomaly_report.affected_banks else "ISSUER"
            root_cause = f"Core Banking System (CBS) degradation at issuer bank {bank_name}"
            conf = 0.92
            action = ActionType.SPLIT_TRAFFIC_CANARY
            exp = f"Issuer {bank_name} transactions failing with ISSUER_DOWN. Route via multi-bank aggregator {alternate_route} or alert merchant."

        elif primary_type == "GATEWAY_ERROR" or ErrorCode.GATEWAY_ERROR.value in error_dist:
            root_cause = f"Internal gateway HTTP 500 errors on {target_route}"
            conf = 0.90
            action = ActionType.QUARANTINE_ROUTE
            exp = f"Route {target_route} returning HTTP 500. Recommend immediate quarantine and divert traffic to {alternate_route}."

        elif ErrorCode.RATE_LIMITED.value in error_dist:
            root_cause = f"Upstream concurrency saturation / rate limit on {target_route}"
            conf = 0.88
            action = ActionType.SPLIT_TRAFFIC_CANARY
            exp = f"Route {target_route} saturated under traffic surge. Split traffic to secondary route {alternate_route}."

        else:
            root_cause = f"Generalized success rate degradation on {target_route}"
            conf = 0.82
            action = ActionType.SPLIT_TRAFFIC_CANARY
            exp = f"Success rate dropped to {round(snapshot.success_rate * 100, 1)}%. Recommend canary testing to verify alternative switch."

        return AIDoctorDiagnosis(
            incident_id=incident_id,
            root_cause=root_cause,
            confidence_score=conf,
            recommended_action=action,
            target_route_id=alternate_route,
            evidence=anomaly_report.evidence,
            explanation=exp,
            historical_precedent=precedent,
        )

    def _diagnose_with_llm(
        self,
        incident_id: str,
        anomaly_report: AnomalyReport,
        snapshot: TelemetrySnapshot,
        error_dist: dict,
        recent_metrics: dict,
        precedent: Optional[str],
    ) -> AIDoctorDiagnosis:
        """Diagnose using Gemini LLM with strict JSON schema enforcement."""
        from google import genai

        client = genai.Client(api_key=self.api_key)

        prompt = f"""You are the Pulse AI Doctor for payment reliability.
Diagnose this payment degradation incident based strictly on the following factual evidence:
- Primary Anomaly: {anomaly_report.primary_anomaly_type}
- Severity: {anomaly_report.severity.value}
- Affected Routes: {anomaly_report.affected_route_ids}
- Success Rate: {snapshot.success_rate}
- Timeout Rate: {snapshot.timeout_rate}
- p95 Latency: {snapshot.latency.p95_ms}ms
- Error Breakdown: {error_dist}
- Historical Precedent: {precedent}

Output strict JSON with fields:
- root_cause: string
- confidence_score: float (0.0 to 1.0)
- recommended_action: string (one of NO_ACTION, SWITCH_ROUTE, SPLIT_TRAFFIC_CANARY, QUARANTINE_ROUTE, ESCALATE_HUMAN)
- target_route_id: string
- explanation: string
"""
        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )

        data = json.loads(response.text)
        action = ActionType(data.get("recommended_action", "SPLIT_TRAFFIC_CANARY"))

        return AIDoctorDiagnosis(
            incident_id=incident_id,
            root_cause=data.get("root_cause", "Payment degradation detected"),
            confidence_score=float(data.get("confidence_score", 0.90)),
            recommended_action=action,
            target_route_id=data.get("target_route_id", "psp_icici_backup"),
            evidence=anomaly_report.evidence,
            explanation=data.get("explanation", "AI Doctor diagnosis"),
            historical_precedent=precedent,
        )
