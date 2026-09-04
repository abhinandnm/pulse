import pytest
from pathlib import Path
from pulse.domain.types import IncidentSeverity, ActionType
from pulse.domain.incident import IncidentRecord, DiagnosticHypothesis
from pulse.memory.repository import IncidentRepository
from pulse.memory.retriever import IncidentRetriever


def make_sample_incident(
    inc_id: str,
    trigger: str,
    root_cause: str,
    target_route: str = None,
    is_resolved: bool = True,
) -> IncidentRecord:
    hyp = DiagnosticHypothesis(
        hypothesis_id=f"hyp_{inc_id}",
        title=f"Hypothesis for {inc_id}",
        description=f"Suspected issue with {root_cause}",
        confidence_score=0.90,
        recommended_action=ActionType.SWITCH_ROUTE,
        target_route_id=target_route,
    )
    return IncidentRecord(
        incident_id=inc_id,
        severity=IncidentSeverity.HIGH,
        trigger_metric=trigger,
        root_cause=root_cause,
        hypotheses=[hyp],
        actions_taken=[ActionType.SWITCH_ROUTE],
        revenue_at_risk_inr=25000.0,
        recovered_revenue_inr=23000.0,
        is_resolved=is_resolved,
    )


class TestIncidentRepository:
    def test_save_and_retrieve(self):
        repo = IncidentRepository()
        inc = make_sample_incident("inc_001", "timeout_rate > 0.05", "PSP timeout spike", "psp_hdfc_direct")
        repo.save_incident(inc)

        retrieved = repo.get_incident("inc_001")
        assert retrieved is not None
        assert retrieved.incident_id == "inc_001"
        assert retrieved.root_cause == "PSP timeout spike"

    def test_persistence(self, tmp_path: Path):
        file_path = tmp_path / "incidents.json"
        repo1 = IncidentRepository(persistence_path=file_path)
        inc1 = make_sample_incident("inc_persist", "latency > 2000ms", "Network lag")
        repo1.save_incident(inc1)

        # Reload in new instance
        repo2 = IncidentRepository(persistence_path=file_path)
        assert repo2.count() == 1
        assert repo2.get_incident("inc_persist") is not None


class TestIncidentRetriever:
    def setup_method(self):
        self.repo = IncidentRepository()
        self.inc_timeout = make_sample_incident(
            "inc_timeout",
            trigger="timeout_rate > 0.10",
            root_cause="PSP A socket timeout spike",
            target_route="psp_hdfc_direct",
        )
        self.inc_bank = make_sample_incident(
            "inc_bank",
            trigger="bank_icici_success_rate < 0.20",
            root_cause="ICICI issuer CBS outage",
            target_route="psp_icici_backup",
        )
        self.inc_auth = make_sample_incident(
            "inc_auth",
            trigger="auth_failures > 50",
            root_cause="SMS OTP gateway degradation",
            target_route="psp_aggregator_fallback",
        )
        self.repo.save_incident(self.inc_timeout)
        self.repo.save_incident(self.inc_bank)
        self.repo.save_incident(self.inc_auth)

        self.retriever = IncidentRetriever(self.repo)

    def test_similarity_search_matches_correct_incident(self):
        # Search for timeout anomaly on psp_hdfc_direct
        matches = self.retriever.find_similar_incidents(
            trigger_metric="timeout_rate > 0.05",
            root_cause_hint="PSP timeout spike",
            target_route="psp_hdfc_direct",
            top_k=2,
        )

        assert len(matches) > 0
        best_match, score = matches[0]
        assert best_match.incident_id == "inc_timeout"
        assert score > 0.30

    def test_similarity_search_matches_bank_outage(self):
        matches = self.retriever.find_similar_incidents(
            trigger_metric="ICICI issuer failure",
            root_cause_hint="CBS outage",
            top_k=1,
        )

        assert len(matches) > 0
        best_match, score = matches[0]
        assert best_match.incident_id == "inc_bank"
