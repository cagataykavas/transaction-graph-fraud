from __future__ import annotations

import json

import pytest

from graphfraud.domain import Transaction
from graphfraud.split_audit import (
    GraphSplitAuditError,
    GraphSplitPolicy,
    audit_graph_split,
)


def tx(transaction_id: str, src: str, dst: str, timestamp: float) -> Transaction:
    return Transaction(transaction_id, src, dst, 100.0, timestamp)


def test_clean_inductive_split_is_accepted() -> None:
    audit = audit_graph_split(
        [tx("train-1", "a", "b", 1.0), tx("train-2", "c", "d", 2.0)],
        [tx("test-1", "e", "f", 10.0)],
    )

    assert audit.accepted is True
    assert audit.overlapping_entity_count == 0
    assert audit.overlapping_edge_count == 0
    assert audit.temporal_gap_seconds == 8.0
    assert audit.findings == ()


def test_entity_contamination_is_aggregated_without_exposing_identity() -> None:
    audit = audit_graph_split(
        [tx("train-1", "customer-sensitive", "b", 1.0)],
        [tx("test-1", "customer-sensitive", "c", 2.0)],
    )

    rendered = json.dumps(audit.to_dict(), sort_keys=True)
    assert audit.accepted is False
    assert audit.test_entity_overlap_rate == 0.5
    assert audit.findings == ("TEST_ENTITY_OVERLAP_LIMIT_EXCEEDED",)
    assert "customer-sensitive" not in rendered


def test_repeated_directed_relationship_is_reported() -> None:
    audit = audit_graph_split(
        [tx("train-1", "a", "b", 1.0)],
        [tx("test-1", "a", "b", 2.0)],
        policy=GraphSplitPolicy(max_test_entity_overlap_rate=1.0),
    )

    assert audit.accepted is False
    assert audit.test_edge_overlap_rate == 1.0
    assert audit.findings == ("TEST_EDGE_OVERLAP_LIMIT_EXCEEDED",)


def test_temporal_mode_can_deliberately_allow_known_entities_and_edges() -> None:
    audit = audit_graph_split(
        [tx("train-1", "a", "b", 1.0)],
        [tx("test-1", "a", "b", 10.0)],
        policy=GraphSplitPolicy(
            max_test_entity_overlap_rate=1.0,
            max_test_edge_overlap_rate=1.0,
            minimum_temporal_gap_seconds=5.0,
        ),
    )

    assert audit.accepted is True
    assert audit.temporal_gap_seconds == 9.0


@pytest.mark.parametrize("test_timestamp", [2.0, 2.5])
def test_temporal_gap_is_strict_and_includes_embargo(test_timestamp: float) -> None:
    audit = audit_graph_split(
        [tx("train-1", "a", "b", 2.0)],
        [tx("test-1", "c", "d", test_timestamp)],
        policy=GraphSplitPolicy(minimum_temporal_gap_seconds=0.5),
    )

    assert audit.accepted is False
    assert audit.findings == ("TEMPORAL_GAP_REQUIREMENT_BREACHED",)


def test_duplicate_transaction_ids_fail_closed() -> None:
    with pytest.raises(GraphSplitAuditError, match="disjoint"):
        audit_graph_split(
            [tx("duplicate", "a", "b", 1.0)],
            [tx("duplicate", "c", "d", 2.0)],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("amount", float("nan")), ("timestamp", float("inf"))],
)
def test_non_finite_transaction_evidence_fails_closed(field: str, value: float) -> None:
    values = {
        "transaction_id": "train-1",
        "src": "a",
        "dst": "b",
        "amount": 100.0,
        "timestamp": 1.0,
    }
    values[field] = value
    invalid = Transaction(**values)

    with pytest.raises(GraphSplitAuditError, match="finite"):
        audit_graph_split([invalid], [tx("test-1", "c", "d", 2.0)])


def test_budget_is_enforced_before_member_validation() -> None:
    invalid = Transaction("bad", "a", "b", float("nan"), 3.0)

    with pytest.raises(GraphSplitAuditError, match="budget"):
        audit_graph_split(
            [tx("train-1", "a", "b", 1.0), tx("train-2", "c", "d", 2.0)],
            [invalid],
            policy=GraphSplitPolicy(max_transactions=2),
        )


def test_evidence_is_deterministic_and_binds_policy_and_inputs() -> None:
    train = [tx("train-1", "a", "b", 1.0)]
    test = [tx("test-1", "c", "d", 2.0)]
    first = audit_graph_split(train, test)
    repeated = audit_graph_split(list(train), list(test))
    relaxed = audit_graph_split(
        train,
        test,
        policy=GraphSplitPolicy(max_test_entity_overlap_rate=0.1),
    )
    changed = audit_graph_split(train, [tx("test-1", "c", "e", 2.0)])

    assert first == repeated
    assert relaxed.accepted is True
    assert relaxed.evidence_sha256 != first.evidence_sha256
    assert changed.test_sha256 != first.test_sha256
    assert changed.evidence_sha256 != first.evidence_sha256


@pytest.mark.parametrize("value", [float("nan"), "0.1", True, -0.1, 1.1])
def test_invalid_policy_fails_before_split_processing(value: object) -> None:
    with pytest.raises(GraphSplitAuditError, match=r"in \[0, 1\]"):
        audit_graph_split(
            [],
            [],
            policy=GraphSplitPolicy(max_test_entity_overlap_rate=value),  # type: ignore[arg-type]
        )
