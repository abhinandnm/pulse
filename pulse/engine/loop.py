import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, List, Callable, Any
from pydantic import BaseModel, Field, ConfigDict

from pulse.domain.types import (
    OperatingMode,
    SystemState,
    ActionType,
    CanaryGateStatus,
    IncidentSeverity,
)
from pulse.domain.transaction import TransactionResult
from pulse.domain.incident import IncidentRecord, DiagnosticHypothesis
from pulse.domain.events import AuditEvent
from pulse.domain.canary import CanaryState
from pulse.domain.telemetry import TelemetrySnapshot
from pulse.fsm.machine import PulseStateMachine
from pulse.observer.collector import TelemetryObserver
from pulse.observer.anomaly import StatisticalAnomalyDetector, AnomalyReport
from pulse.accountant.engine import RevenueAccountant, FinancialExposureReport
from pulse.doctor.tools import DiagnosticToolkit
from pulse.doctor.ai_doctor import AIDoctor, AIDoctorDiagnosis
from pulse.counterfactual.engine import CounterfactualEngine
from pulse.canary.controller import CanarySafetyController, CanaryEvaluationResult
from pulse.safety.quarantine import QuarantineManager
from pulse.safety.anti_flapping import AntiFlappingController
from pulse.memory.repository import IncidentRepository


class PulseLoopResult(BaseModel):
    """Execution summary of a single control loop iteration."""
    model_config = ConfigDict(frozen=True)

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    operating_mode: OperatingMode
    system_state: SystemState
    anomaly_detected: bool = False
    active_incident_id: Optional[str] = None
    diagnosis: Optional[AIDoctorDiagnosis] = None
    exposure_report: Optional[FinancialExposureReport] = None
    chosen_action: Optional[ActionType] = None
    active_canary_state: Optional[CanaryState] = None
    action_executed: bool = False
    audit_events: List[AuditEvent] = Field(default_factory=list)


class AutonomousControlLoop:
    """
    Central Autonomous Control Engine connecting all Pulse components:
    Observer -> Anomaly Detector -> Accountant -> AI Doctor ->
    Counterfactual Engine -> FSM -> Canary Safety Controller ->
    Quarantine/Anti-flapping -> Incident Memory.
    """

    def __init__(
        self,
        observer: TelemetryObserver,
        operating_mode: OperatingMode = OperatingMode.AUTONOMOUS,
        repository: Optional[IncidentRepository] = None,
        on_audit_event: Optional[Callable[[AuditEvent], None]] = None,
    ):
        self.operating_mode = operating_mode
        self.observer = observer
        self.repository = repository or IncidentRepository()
        self.on_audit_event = on_audit_event

        # Subsystems
        self.fsm = PulseStateMachine(initial_state=SystemState.HEALTHY)
        self.detector = StatisticalAnomalyDetector(baseline_manager=observer.baseline_manager)
        self.accountant = RevenueAccountant(baseline_manager=observer.baseline_manager)
        self.toolkit = DiagnosticToolkit(observer=observer, repository=self.repository)
        self.doctor = AIDoctor(toolkit=self.toolkit)
        self.counterfactual = CounterfactualEngine(baseline_manager=observer.baseline_manager)
        self.canary_controller = CanarySafetyController()
        self.quarantine_mgr = QuarantineManager()
        self.anti_flapping = AntiFlappingController(quarantine_manager=self.quarantine_mgr)

        # Active state tracking
        self.active_incident: Optional[IncidentRecord] = None
        self.active_canary_state: Optional[CanaryState] = None
        self.pending_assisted_decision = None
        self._audit_trail: List[AuditEvent] = []

    def set_operating_mode(self, mode: OperatingMode) -> None:
        """Switch between OBSERVE, ASSISTED, and AUTONOMOUS modes."""
        self.operating_mode = mode
        self._record_audit("OPERATOR", "SET_MODE", f"Operating mode switched to {mode.value}")

    def step(self, candidate_canary_results: Optional[List[TransactionResult]] = None) -> PulseLoopResult:
        """
        Execute one iteration of the control loop:
        Poll telemetry -> Detect anomalies -> Quantify exposure ->
        Diagnose -> Counterfactual -> Actuate FSM & Safety.
        """
        audit_records_this_step: List[AuditEvent] = []
        snapshot = self.observer.get_snapshot()

        # 1. State: CANARY in progress
        if self.fsm.current_state == SystemState.CANARY and self.active_canary_state:
            canary_results = candidate_canary_results or []
            updated_state, eval_res = self.canary_controller.evaluate_results(
                canary_state=self.active_canary_state,
                candidate_results=canary_results,
            )
            self.active_canary_state = updated_state

            if eval_res.should_rollback:
                # Rollback triggered by gate failure
                self.fsm.transition_to(SystemState.ROLLED_BACK, reason=eval_res.reason)
                audit = self._record_audit("CANARY_CONTROLLER", ActionType.ROLLBACK, eval_res.reason)
                audit_records_this_step.append(audit)

                # Quarantine candidate route
                quar_rec = self.quarantine_mgr.quarantine_route(
                    route_id=updated_state.target_route_id,
                    reason=f"Rolled back during canary: {eval_res.reason}",
                )
                self.fsm.transition_to(SystemState.QUARANTINED, reason=f"Quarantined {quar_rec.route_id} for {quar_rec.cooldown_seconds}s")
                self.observer.quarantine_route(quar_rec.route_id, quar_rec.cooldown_seconds)

                # Close incident as resolved via rollback
                if self.active_incident:
                    resolved_inc = IncidentRecord(
                        incident_id=self.active_incident.incident_id,
                        severity=self.active_incident.severity,
                        detected_at=self.active_incident.detected_at,
                        resolved_at=datetime.now(timezone.utc),
                        trigger_metric=self.active_incident.trigger_metric,
                        root_cause=self.active_incident.root_cause,
                        hypotheses=self.active_incident.hypotheses,
                        actions_taken=self.active_incident.actions_taken + [ActionType.ROLLBACK, ActionType.QUARANTINE_ROUTE],
                        revenue_at_risk_inr=self.active_incident.revenue_at_risk_inr,
                        recovered_revenue_inr=0.0,
                        is_resolved=True,
                    )
                    self.repository.save_incident(resolved_inc)
                    self.active_incident = None

                self.active_canary_state = None
                return PulseLoopResult(
                    operating_mode=self.operating_mode,
                    system_state=self.fsm.current_state,
                    active_canary_state=updated_state,
                    action_executed=True,
                    chosen_action=ActionType.ROLLBACK,
                    audit_events=audit_records_this_step,
                )

            elif eval_res.should_promote_full:
                # Full Promotion!
                self.fsm.transition_to(SystemState.PROMOTED, reason=eval_res.reason)
                audit = self._record_audit("CANARY_CONTROLLER", "PROMOTE", eval_res.reason)
                audit_records_this_step.append(audit)

                # Restore system to healthy
                self.fsm.transition_to(SystemState.HEALTHY, reason="Candidate promoted to 100% and verified stable")

                # Quantify recovered revenue prevented
                if self.active_incident:
                    recovered = self.accountant.calculate_prevented_loss(
                        degraded_sr=0.70,
                        recovered_sr=0.98,
                        post_recovery_volume=500,
                    )
                    resolved_inc = IncidentRecord(
                        incident_id=self.active_incident.incident_id,
                        severity=self.active_incident.severity,
                        detected_at=self.active_incident.detected_at,
                        resolved_at=datetime.now(timezone.utc),
                        trigger_metric=self.active_incident.trigger_metric,
                        root_cause=self.active_incident.root_cause,
                        hypotheses=self.active_incident.hypotheses,
                        actions_taken=self.active_incident.actions_taken + [ActionType.SPLIT_TRAFFIC_CANARY],
                        revenue_at_risk_inr=self.active_incident.revenue_at_risk_inr,
                        recovered_revenue_inr=recovered,
                        is_resolved=True,
                    )
                    self.repository.save_incident(resolved_inc)
                    self.active_incident = None

                self.active_canary_state = None
                return PulseLoopResult(
                    operating_mode=self.operating_mode,
                    system_state=self.fsm.current_state,
                    active_canary_state=updated_state,
                    action_executed=True,
                    chosen_action=ActionType.SPLIT_TRAFFIC_CANARY,
                    audit_events=audit_records_this_step,
                )

            else:
                # Canary still advancing / pending
                return PulseLoopResult(
                    operating_mode=self.operating_mode,
                    system_state=self.fsm.current_state,
                    active_canary_state=updated_state,
                    action_executed=False,
                    audit_events=audit_records_this_step,
                )

        # 2. Statistical Anomaly Detection
        report = self.detector.evaluate(snapshot)

        if not report.is_anomaly:
            # System is nominal
            if self.fsm.current_state in (SystemState.QUARANTINED, SystemState.DEGRADED):
                self.fsm.transition_to(SystemState.HEALTHY, reason="Telemetry returned to healthy SLO limits")
            return PulseLoopResult(
                operating_mode=self.operating_mode,
                system_state=self.fsm.current_state,
                anomaly_detected=False,
                audit_events=audit_records_this_step,
            )

        # 3. Anomaly Detected -> FSM: DEGRADED
        if self.fsm.current_state == SystemState.HEALTHY:
            self.fsm.transition_to(SystemState.DEGRADED, reason=f"Anomaly detected: {report.primary_anomaly_type}")
            audit = self._record_audit("ANOMALY_DETECTOR", "ALERT", f"Detected {report.primary_anomaly_type} (sev: {report.severity.value})")
            audit_records_this_step.append(audit)

        # 4. Accountant: Calculate Financial Exposure
        exposure = self.accountant.calculate_exposure(snapshot)

        # 5. FSM: DIAGNOSING
        if self.fsm.current_state == SystemState.DEGRADED:
            self.fsm.transition_to(SystemState.DIAGNOSING, reason="AI Doctor initiating diagnosis")

        inc_id = f"inc_{uuid.uuid4().hex[:8]}"
        diagnosis = self.doctor.diagnose(incident_id=inc_id, anomaly_report=report, snapshot=snapshot)
        audit_doc = self._record_audit("AI_DOCTOR", diagnosis.recommended_action, f"Diagnosis: {diagnosis.root_cause} (conf: {diagnosis.confidence_score})")
        audit_records_this_step.append(audit_doc)

        # Create Active Incident Record
        self.active_incident = IncidentRecord(
            incident_id=inc_id,
            severity=report.severity,
            detected_at=datetime.now(timezone.utc),
            trigger_metric=report.primary_anomaly_type,
            root_cause=diagnosis.root_cause,
            hypotheses=[
                DiagnosticHypothesis(
                    title=diagnosis.root_cause,
                    description=diagnosis.explanation,
                    confidence_score=diagnosis.confidence_score,
                    supporting_evidence=diagnosis.evidence,
                    recommended_action=diagnosis.recommended_action,
                    target_route_id=diagnosis.target_route_id,
                )
            ],
            actions_taken=[],
            revenue_at_risk_inr=exposure.current_exposure_inr,
            recovered_revenue_inr=0.0,
            is_resolved=False,
        )
        self.repository.save_incident(self.active_incident)

        # 6. FSM: EVALUATING
        self.fsm.transition_to(SystemState.EVALUATING, reason="Evaluating counterfactual recovery actions")

        degraded_route = report.affected_route_ids[0] if report.affected_route_ids else None
        cf_decision = self.counterfactual.evaluate_options(
            snapshot=snapshot,
            degraded_route_id=degraded_route,
            incident_id=inc_id,
        )

        chosen_action = cf_decision.chosen_action
        target_route = cf_decision.chosen_route_id or "psp_icici_backup"

        # 7. Operating Mode Decision Gates
        if self.operating_mode == OperatingMode.OBSERVE:
            audit = self._record_audit("PULSE_OBSERVE", chosen_action, f"Observe mode: Recommended {chosen_action.value} to {target_route}")
            audit_records_this_step.append(audit)
            return PulseLoopResult(
                operating_mode=self.operating_mode,
                system_state=self.fsm.current_state,
                anomaly_detected=True,
                active_incident_id=inc_id,
                diagnosis=diagnosis,
                exposure_report=exposure,
                chosen_action=chosen_action,
                action_executed=False,
                audit_events=audit_records_this_step,
            )

        elif self.operating_mode == OperatingMode.ASSISTED:
            self.pending_assisted_decision = cf_decision
            audit = self._record_audit("PULSE_ASSISTED", chosen_action, f"Assisted mode: Awaiting human operator approval for {chosen_action.value}")
            audit_records_this_step.append(audit)
            return PulseLoopResult(
                operating_mode=self.operating_mode,
                system_state=self.fsm.current_state,
                anomaly_detected=True,
                active_incident_id=inc_id,
                diagnosis=diagnosis,
                exposure_report=exposure,
                chosen_action=chosen_action,
                action_executed=False,
                audit_events=audit_records_this_step,
            )

        # AUTONOMOUS MODE -> Actuate Recovery!
        if chosen_action == ActionType.SPLIT_TRAFFIC_CANARY:
            self.fsm.transition_to(SystemState.CANARY, reason=f"Starting autonomous canary on {target_route}")
            self.active_canary_state = CanaryState(
                target_route_id=target_route,
                fallback_route_id=degraded_route or "psp_hdfc_direct",
                current_traffic_percentage=20,
            )
            audit = self._record_audit("SAFETY_CONTROLLER", ActionType.SPLIT_TRAFFIC_CANARY, f"Initiated 20% canary split to {target_route}")
            audit_records_this_step.append(audit)

        elif chosen_action == ActionType.QUARANTINE_ROUTE:
            quar_rec = self.quarantine_mgr.quarantine_route(degraded_route or "psp_hdfc_direct", reason="Autonomous quarantine")
            self.fsm.transition_to(SystemState.QUARANTINED, reason=f"Autonomous quarantine of {quar_rec.route_id}")
            self.observer.quarantine_route(quar_rec.route_id, quar_rec.cooldown_seconds)
            audit = self._record_audit("SAFETY_CONTROLLER", ActionType.QUARANTINE_ROUTE, f"Quarantined {quar_rec.route_id}")
            audit_records_this_step.append(audit)

        elif chosen_action == ActionType.ESCALATE_HUMAN:
            self.fsm.transition_to(SystemState.ESCALATED, reason="Autonomous loop escalated to on-call human")
            audit = self._record_audit("SAFETY_CONTROLLER", ActionType.ESCALATE_HUMAN, "Escalated to human operator")
            audit_records_this_step.append(audit)

        return PulseLoopResult(
            operating_mode=self.operating_mode,
            system_state=self.fsm.current_state,
            anomaly_detected=True,
            active_incident_id=inc_id,
            diagnosis=diagnosis,
            exposure_report=exposure,
            chosen_action=chosen_action,
            active_canary_state=self.active_canary_state,
            action_executed=True,
            audit_events=audit_records_this_step,
        )

    def _record_audit(self, actor: str, action: Any, description: str) -> AuditEvent:
        act_val = action.value if hasattr(action, "value") else str(action)
        event = AuditEvent(
            actor=actor,
            action=act_val,
            description=description,
            timestamp=datetime.now(timezone.utc),
        )
        self._audit_trail.append(event)
        if self.on_audit_event:
            self.on_audit_event(event)
        return event
