from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import app
from graphfraud.detectors import detect_cycles, detect_fan_patterns, detect_layering_chains
from graphfraud.engine import GraphFraudEngine
from graphfraud.synthetic import synthetic_transactions


def test_synthetic_dataset_contains_expected_typologies():
    txs = synthetic_transactions(seed=42)
    assert detect_cycles(txs)
    assert any(item.finding_type == "fan_in" for item in detect_fan_patterns(txs))
    assert detect_layering_chains(txs)


def test_engine_ranks_known_suspicious_entities():
    result = GraphFraudEngine().analyze(synthetic_transactions(seed=42))
    ranked = {item["entity_id"]: item for item in result["entities"]}
    assert ranked["risk_mule"]["score"] > 0
    assert ranked["risk_cycle_a"]["reasons"]
    assert result["findings"]


def test_demo_api_returns_analysis():
    client = TestClient(app)
    response = client.get("/demo?seed=42")
    assert response.status_code == 200
    payload = response.json()
    assert payload["transaction_count"] > 100
    assert len(payload["findings"]) >= 3
