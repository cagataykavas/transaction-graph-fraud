from __future__ import annotations

import math

from .detectors import detect_cycles, detect_fan_patterns, detect_layering_chains
from .domain import EntityRisk, GraphFinding, Transaction
from .features import entity_features


def _severity(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.65:
        return "high"
    if score >= 0.40:
        return "medium"
    return "low"


class GraphFraudEngine:
    """Combines graph features and explicit typology detectors into ranked findings."""

    def analyze(self, transactions: list[Transaction]) -> dict[str, object]:
        findings = self.findings(transactions)
        risks = self.entity_risks(transactions, findings)
        return {
            "transaction_count": len(transactions),
            "entity_count": len(risks),
            "findings": [finding.as_dict() for finding in findings],
            "entities": [risk.as_dict() for risk in sorted(risks.values(), key=lambda item: item.score, reverse=True)],
        }

    def findings(self, transactions: list[Transaction]) -> list[GraphFinding]:
        findings = [
            *detect_cycles(transactions),
            *detect_fan_patterns(transactions),
            *detect_layering_chains(transactions),
        ]
        dedup: dict[str, GraphFinding] = {finding.finding_id: finding for finding in findings}
        return sorted(dedup.values(), key=lambda item: item.score, reverse=True)

    def entity_risks(
        self,
        transactions: list[Transaction],
        findings: list[GraphFinding] | None = None,
    ) -> dict[str, EntityRisk]:
        features = entity_features(transactions)
        active_findings = findings if findings is not None else self.findings(transactions)
        finding_scores: dict[str, list[tuple[float, str]]] = {entity: [] for entity in features}
        for finding in active_findings:
            for entity in finding.entities:
                if entity in finding_scores:
                    finding_scores[entity].append((finding.score, finding.finding_type))

        risks: dict[str, EntityRisk] = {}
        for entity, f in features.items():
            degree = math.log1p(f["unique_peers"]) / 4.0
            velocity = math.log1p(f["transaction_velocity_per_hour"]) / 4.0
            imbalance = min(1.0, abs(math.log((f["sent_amount"] + 1.0) / (f["received_amount"] + 1.0))) / 4.0)
            graph_signal = min(1.0, f["pagerank"] * 10.0 + f["clustering"] * 0.25)
            typology_scores = [score for score, _ in finding_scores.get(entity, [])]
            typology = max(typology_scores, default=0.0)
            score = min(1.0, 0.20 * degree + 0.20 * velocity + 0.20 * imbalance + 0.10 * graph_signal + 0.30 * typology)
            reasons = []
            if f["unique_peers"] >= 5:
                reasons.append("many counterparties")
            if f["transaction_velocity_per_hour"] >= 5:
                reasons.append("high transaction velocity")
            if imbalance >= 0.45:
                reasons.append("large inbound/outbound flow imbalance")
            reasons.extend(sorted({kind.replace("_", " ") for _, kind in finding_scores.get(entity, [])}))
            risks[entity] = EntityRisk(
                entity_id=entity,
                score=score,
                severity=_severity(score),
                features=f,
                reasons=tuple(reasons),
            )
        return risks
