from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass

from .domain import GraphFinding

SCHEMA_VERSION = 1
WEIGHTS = {
    "counterparty_breadth": 0.20,
    "transaction_velocity": 0.20,
    "flow_imbalance": 0.20,
    "graph_centrality": 0.10,
    "detected_typology": 0.30,
}
REQUIRED_FEATURES = {
    "unique_peers",
    "transaction_velocity_per_hour",
    "sent_amount",
    "received_amount",
    "pagerank",
    "clustering",
}


@dataclass(frozen=True)
class RiskContribution:
    component: str
    source_value: float
    normalized_value: float
    weight: float
    contribution: float


@dataclass(frozen=True)
class RiskAttribution:
    schema_version: int
    predicted_score: float
    pre_cap_score: float
    cap_adjustment: float
    dominant_component: str
    typology_finding_ids: tuple[str, ...]
    contributions: tuple[RiskContribution, ...]
    evidence_sha256: str

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["typology_finding_ids"] = list(self.typology_finding_ids)
        payload["contributions"] = [asdict(item) for item in self.contributions]
        return payload


def _finite_nonnegative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def _contribution(component: str, source: float, normalized: float) -> RiskContribution:
    weight = WEIGHTS[component]
    return RiskContribution(
        component=component,
        source_value=source,
        normalized_value=normalized,
        weight=weight,
        contribution=weight * normalized,
    )


def explain_entity_risk(
    features: dict[str, float],
    matched_findings: list[GraphFinding],
) -> RiskAttribution:
    """Reproduce one entity score as an exact additive attribution artifact."""

    missing = REQUIRED_FEATURES - set(features)
    if missing:
        raise ValueError(f"missing attribution features: {', '.join(sorted(missing))}")
    peers = _finite_nonnegative(features["unique_peers"], "unique_peers")
    velocity = _finite_nonnegative(
        features["transaction_velocity_per_hour"], "transaction_velocity_per_hour"
    )
    sent = _finite_nonnegative(features["sent_amount"], "sent_amount")
    received = _finite_nonnegative(features["received_amount"], "received_amount")
    pagerank = _finite_nonnegative(features["pagerank"], "pagerank")
    clustering = _finite_nonnegative(features["clustering"], "clustering")
    if pagerank > 1.0 or clustering > 1.0:
        raise ValueError("pagerank and clustering must be within [0, 1]")

    finding_ids: set[str] = set()
    finding_scores: list[tuple[str, float]] = []
    for finding in matched_findings:
        if finding.finding_id in finding_ids:
            raise ValueError("matched findings contain a duplicate finding_id")
        finding_ids.add(finding.finding_id)
        score = _finite_nonnegative(finding.score, "finding score")
        if score > 1.0:
            raise ValueError("finding score must be within [0, 1]")
        finding_scores.append((finding.finding_id, score))
    typology = max((score for _, score in finding_scores), default=0.0)
    winning_findings = tuple(
        sorted(item for item, score in finding_scores if score == typology)
    )

    degree_normalized = math.log1p(peers) / 4.0
    velocity_normalized = math.log1p(velocity) / 4.0
    imbalance_source = abs(math.log((sent + 1.0) / (received + 1.0)))
    imbalance_normalized = min(1.0, imbalance_source / 4.0)
    centrality_source = pagerank * 10.0 + clustering * 0.25
    centrality_normalized = min(1.0, centrality_source)
    contributions = (
        _contribution("counterparty_breadth", peers, degree_normalized),
        _contribution("transaction_velocity", velocity, velocity_normalized),
        _contribution("flow_imbalance", imbalance_source, imbalance_normalized),
        _contribution("graph_centrality", centrality_source, centrality_normalized),
        _contribution("detected_typology", typology, typology),
    )
    pre_cap_score = math.fsum(item.contribution for item in contributions)
    predicted_score = min(1.0, pre_cap_score)
    cap_adjustment = predicted_score - pre_cap_score
    dominant = max(contributions, key=lambda item: item.contribution).component
    evidence = {
        "cap_adjustment": cap_adjustment,
        "contributions": [asdict(item) for item in contributions],
        "dominant_component": dominant,
        "pre_cap_score": pre_cap_score,
        "predicted_score": predicted_score,
        "schema_version": SCHEMA_VERSION,
        "typology_finding_ids": winning_findings,
    }
    canonical = json.dumps(
        evidence,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return RiskAttribution(
        schema_version=SCHEMA_VERSION,
        predicted_score=predicted_score,
        pre_cap_score=pre_cap_score,
        cap_adjustment=cap_adjustment,
        dominant_component=dominant,
        typology_finding_ids=winning_findings,
        contributions=contributions,
        evidence_sha256=hashlib.sha256(canonical).hexdigest(),
    )
