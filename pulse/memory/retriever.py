import re
from typing import List, Tuple, Optional, Set
from pulse.domain.incident import IncidentRecord
from pulse.memory.repository import IncidentRepository


def _tokenize(text: str) -> Set[str]:
    """Tokenize text into lowercase alphanumeric words."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return set(words)


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Calculate Jaccard similarity index between two sets of tokens."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return round(intersection / union, 4) if union > 0 else 0.0


class IncidentRetriever:
    """
    Retrieves historically similar incidents from operational memory
    to provide the AI Doctor with grounded historical precedent.
    """

    def __init__(self, repository: IncidentRepository):
        self.repository = repository

    def find_similar_incidents(
        self,
        trigger_metric: str,
        root_cause_hint: Optional[str] = None,
        target_route: Optional[str] = None,
        top_k: int = 3,
        min_similarity: float = 0.15,
    ) -> List[Tuple[IncidentRecord, float]]:
        """
        Search historical incidents by similarity to current operational anomaly.
        Returns a list of (IncidentRecord, similarity_score) tuples sorted descending.
        """
        query_tokens = _tokenize(trigger_metric)
        if root_cause_hint:
            query_tokens.update(_tokenize(root_cause_hint))
        if target_route:
            query_tokens.update(_tokenize(target_route))

        all_incidents = self.repository.list_incidents(limit=200)
        scored: List[Tuple[IncidentRecord, float]] = []

        for inc in all_incidents:
            doc_tokens = _tokenize(inc.trigger_metric)
            doc_tokens.update(_tokenize(inc.root_cause))
            for hyp in inc.hypotheses:
                doc_tokens.update(_tokenize(hyp.title))
                doc_tokens.update(_tokenize(hyp.description))
                if hyp.target_route_id:
                    doc_tokens.add(hyp.target_route_id.lower())

            similarity = jaccard_similarity(query_tokens, doc_tokens)

            # Bonus for exact route match
            if target_route and target_route.lower() in doc_tokens:
                similarity = min(1.0, round(similarity + 0.25, 4))

            if similarity >= min_similarity:
                scored.append((inc, similarity))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]
