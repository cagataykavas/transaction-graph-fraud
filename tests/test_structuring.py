from __future__ import annotations

import math

import pytest

from graphfraud.domain import Transaction
from graphfraud.engine import GraphFraudEngine
from graphfraud.structuring import StructuringPolicy, detect_threshold_structuring
from graphfraud.synthetic import synthetic_transactions


def transaction(
    transaction_id: str,
    src: str,
    dst: str,
    amount: float,
    timestamp: float,
    currency: str = "USD",
) -> Transaction:
    return Transaction(transaction_id, src, dst, amount, timestamp, currency)


def structured_rows() -> list[Transaction]:
    return [
        transaction("split-1", "peer-a", "hub", 2_600, 0),
        transaction("split-2", "peer-b", "hub", 2_550, 60),
        transaction("split-3", "peer-c", "hub", 2_500, 120),
        transaction("split-4", "peer-d", "hub", 2_450, 180),
    ]


def test_detects_currency_scoped_sub_threshold_aggregation():
    finding = detect_threshold_structuring(structured_rows())[0]

    assert finding.finding_type == "threshold_structuring"
    assert finding.entities == ("hub", "peer-a", "peer-b", "peer-c", "peer-d")
    assert finding.transaction_ids == ("split-1", "split-2", "split-3", "split-4")
    assert finding.evidence == {
        "direction": "fan_in",
        "currency": "USD",
        "transaction_count": 4,
        "distinct_peer_count": 4,
        "aggregate_amount": 10_100.0,
        "maximum_individual_amount": 2_600,
        "review_threshold": 10_000.0,
        "window_seconds": 3_600.0,
        "observed_span_seconds": 180,
        "all_transfers_below_threshold": True,
    }


def test_results_are_order_invariant():
    forward = detect_threshold_structuring(structured_rows())
    reverse = detect_threshold_structuring(list(reversed(structured_rows())))

    assert forward == reverse


def test_detects_outbound_split_transfer_aggregation():
    rows = [
        transaction(f"out-{index}", "hub", f"peer-{index}", 2_500, index * 60)
        for index in range(4)
    ]

    finding = detect_threshold_structuring(rows)[0]

    assert finding.evidence["direction"] == "fan_out"
    assert finding.entities[0] == "hub"


def test_mixed_currencies_are_never_aggregated_together():
    rows = [
        transaction("usd-1", "a", "hub", 2_600, 0, "USD"),
        transaction("usd-2", "b", "hub", 2_600, 60, "USD"),
        transaction("eur-1", "c", "hub", 2_600, 120, "EUR"),
        transaction("eur-2", "d", "hub", 2_600, 180, "EUR"),
    ]

    assert detect_threshold_structuring(rows) == []


def test_over_threshold_and_out_of_window_transfers_do_not_qualify():
    rows = [
        transaction("large", "a", "hub", 10_000, 0),
        transaction("small-1", "b", "hub", 2_600, 10),
        transaction("small-2", "c", "hub", 2_600, 20),
        transaction("small-3", "d", "hub", 2_600, 30),
        transaction("late", "e", "hub", 2_600, 4_000),
    ]

    assert detect_threshold_structuring(rows) == []


def test_invalid_or_unbounded_evidence_fails_closed():
    duplicate = structured_rows() + [structured_rows()[0]]
    with pytest.raises(ValueError, match="must be unique"):
        detect_threshold_structuring(duplicate)
    with pytest.raises(ValueError, match="analysis budget"):
        detect_threshold_structuring(
            structured_rows(),
            policy=StructuringPolicy(max_transactions=3),
        )
    with pytest.raises(ValueError, match="amounts must be finite"):
        detect_threshold_structuring([transaction("nan", "a", "hub", math.nan, 0)])


def test_engine_surfaces_synthetic_structuring_evidence():
    result = GraphFraudEngine().analyze(synthetic_transactions(seed=42))
    findings = [
        item
        for item in result["findings"]
        if item["finding_type"] == "threshold_structuring"
    ]
    ranked = {item["entity_id"]: item for item in result["entities"]}

    assert findings
    assert findings[0]["evidence"]["currency"] == "USD"
    assert "threshold structuring" in ranked["risk_structuring_hub"]["reasons"]
