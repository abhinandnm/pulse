import json
from pathlib import Path
from typing import Dict, List, Optional
from pulse.domain.incident import IncidentRecord


class IncidentRepository:
    """
    Stores and manages historical and active incident records.
    Provides fast memory lookup with optional JSON persistence.
    """

    def __init__(self, persistence_path: Optional[Path] = None):
        self._incidents: Dict[str, IncidentRecord] = {}
        self.persistence_path = persistence_path
        if persistence_path and persistence_path.exists():
            self._load()

    def save_incident(self, incident: IncidentRecord) -> None:
        """Add or update an incident record."""
        self._incidents[incident.incident_id] = incident
        if self.persistence_path:
            self._persist()

    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]:
        return self._incidents.get(incident_id)

    def list_incidents(
        self,
        limit: int = 50,
        unresolved_only: bool = False,
    ) -> List[IncidentRecord]:
        """List incidents sorted by detected_at descending."""
        records = list(self._incidents.values())
        if unresolved_only:
            records = [r for r in records if not r.is_resolved]
        records.sort(key=lambda r: r.detected_at, reverse=True)
        return records[:limit]

    def count(self) -> int:
        return len(self._incidents)

    def clear(self) -> None:
        self._incidents.clear()
        if self.persistence_path and self.persistence_path.exists():
            self.persistence_path.unlink()

    def _persist(self) -> None:
        if not self.persistence_path:
            return
        data = [json.loads(inc.model_dump_json()) for inc in self._incidents.values()]
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.persistence_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        if not self.persistence_path or not self.persistence_path.exists():
            return
        try:
            with open(self.persistence_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    inc = IncidentRecord.model_validate(item)
                    self._incidents[inc.incident_id] = inc
        except Exception:
            pass
