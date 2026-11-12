from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.api import app
from graphfraud.domain import GraphFinding
from graphfraud.engine import GraphFraudEngine
from graphfraud.risk_attribution import explain_entity_risk
from graphfraud.synthetic import synthetic_transactions


def _features(**overrides: float) -> dict[str, float]:
    result = {
        "unique_peers": 4.0,
        "transaction_velocity_per_hour": 6.0,
        "sent_amount": 10_000.0,
        "received_amount": 8_000.0,
        "pagerank": 0.04,
        "clustering": 0.20,
    }
    result.update(overrides)
    return result


def _finding(finding_id: str = "finding-1", score: float = 0.8) -> GraphFinding:
    return GraphFinding(
        finding_id=finding_id,
        finding_type="rapid_fund_cycle",
        entities=("entity-1",),
        transaction_ids=("tx-1",),
        score=score,
        severity="high",
        explanation="Synthetic finding for attribution testing.",
    )


def test_engine_score_is_exactly_reconstructed_for_every_entity() -> None:
    result = GraphFraudEngine().analyze(synthetic_transactions(seed=42))

    for entity in result["entities"]:
        attribution = entity["attribution"]
        reconstructed = (
            math.fsum(item["contribution"] for item in attribution["contributions"])
            + attribution["cap_adjustment"]
        )
        assert reconstructed == pytest.approx(entity["score"], abs=1e-15)
        assert attribution["predicted_score"] == entity["score"]
        assert len(attribution["evidence_sha256"]) == 64


def test_typology_component_names_the_maximal_supporting_findings() -> None:
    explanation = explain_entity_risk(
        _features(),
        [_finding("lower", 0.4), _finding("winner-b", 0.9), _finding("winner-a", 0.9)],
    )

    typology = next(
        item
        for item in explanation.contributions
        if item.component == "detected_typology"
    )
    assert typology.normalized_value == 0.9
    assert typology.contribution == pytest.approx(0.27)
    assert explanation.typology_finding_ids == ("winner-a", "winner-b")


def test_score_saturation_is_reported_as_an_explicit_adjustment() -> None:
    explanation = explain_entity_risk(
        _features(
            unique_peers=1_000_000.0,
            transaction_velocity_per_hour=1_000_000.0,
            sent_amount=1_000_000_000.0,
            received_amount=0.0,
            pagerank=1.0,
            clustering=1.0,
        ),
        [_finding(score=1.0)],
    )

    assert explanation.pre_cap_score > 1.0
    assert explanation.predicted_score == 1.0
    assert explanation.cap_adjustment < 0.0
    reconstructed = (
        math.fsum(item.contribution for item in explanation.contributions)
        + explanation.cap_adjustment
    )
    assert reconstructed == pytest.approx(1.0, abs=1e-15)


def test_no_typology_produces_zero_contribution_and_no_finding_ids() -> None:
    explanation = explain_entity_risk(_features(), [])
    typology = next(
        item
        for item in explanation.contributions
        if item.component == "detected_typology"
    )

    assert typology.contribution == 0.0
    assert explanation.typology_finding_ids == ()


@pytest.mark.parametrize(
    ("features", "message"),
    [
        (_features(pagerank=float("nan")), "pagerank must be finite"),
        (_features(clustering=1.1), "pagerank and clustering"),
        (_features(sent_amount=-1.0), "sent_amount must be finite"),
    ],
)
def test_invalid_feature_evidence_fails_closed(
    features: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        explain_entity_risk(features, [])


def test_attribution_digest_is_deterministic_and_input_sensitive() -> None:
    first = explain_entity_risk(_features(), [_finding()])
    repeated = explain_entity_risk(
        dict(reversed(list(_features().items()))), [_finding()]
    )
    changed = explain_entity_risk(_features(unique_peers=5.0), [_finding()])

    assert first.evidence_sha256 == repeated.evidence_sha256
    assert first.evidence_sha256 != changed.evidence_sha256


def test_api_exposes_the_same_exact_attribution_contract() -> None:
    response = TestClient(app).get("/demo?seed=42")

    assert response.status_code == 200
    entity = response.json()["entities"][0]
    attribution = entity["attribution"]
    assert attribution["schema_version"] == 1
    assert len(attribution["contributions"]) == 5
    assert attribution["predicted_score"] == entity["score"]
