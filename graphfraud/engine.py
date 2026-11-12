from __future__ import annotations

from .detectors import detect_cycles, detect_fan_patterns, detect_layering_chains
from .domain import EntityRisk, GraphFinding, Transaction
from .features import entity_features
from .risk_attribution import explain_entity_risk


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
        entity_findings: dict[str, list[GraphFinding]] = {entity: [] for entity in features}
        for finding in active_findings:
            for entity in finding.entities:
                if entity in entity_findings:
                    entity_findings[entity].append(finding)

        risks: dict[str, EntityRisk] = {}
        for entity, f in features.items():
            matched_findings = entity_findings.get(entity, [])
            attribution = explain_entity_risk(f, matched_findings)
            score = attribution.predicted_score
            imbalance = next(
                item.normalized_value
                for item in attribution.contributions
                if item.component == "flow_imbalance"
            )
            reasons = []
            if f["unique_peers"] >= 5:
                reasons.append("many counterparties")
            if f["transaction_velocity_per_hour"] >= 5:
                reasons.append("high transaction velocity")
            if imbalance >= 0.45:
                reasons.append("large inbound/outbound flow imbalance")
            reasons.extend(sorted({finding.finding_type.replace("_", " ") for finding in matched_findings}))
            risks[entity] = EntityRisk(
                entity_id=entity,
                score=score,
                severity=_severity(score),
                features=f,
                reasons=tuple(reasons),
                attribution=attribution.as_dict(),
            )
        return risks
