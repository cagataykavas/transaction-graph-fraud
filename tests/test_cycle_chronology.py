from __future__ import annotations

from graphfraud.detectors import detect_cycles
from graphfraud.domain import Transaction


def transaction(
    transaction_id: str, src: str, dst: str, timestamp: float, amount: float = 2_000
) -> Transaction:
    return Transaction(transaction_id, src, dst, amount, timestamp)


def test_cycle_requires_chronologically_traversable_edges() -> None:
    impossible = [
        transaction("ab", "a", "b", 0),
        transaction("bc", "b", "c", 20),
        transaction("ca", "c", "a", 10),
    ]

    assert detect_cycles(impossible) == []


def test_cycle_emits_ordered_event_time_evidence() -> None:
    rows = [
        transaction("ca", "c", "a", 30, 1_800),
        transaction("ab", "a", "b", 10, 2_000),
        transaction("bc", "b", "c", 20, 1_900),
    ]

    finding = detect_cycles(rows)[0]

    assert finding.entities == ("a", "b", "c")
    assert finding.transaction_ids == ("ab", "bc", "ca")
    assert finding.evidence["chronological"] is True
    assert finding.evidence["ordered_event_times"] == [10, 20, 30]


def test_parallel_edges_use_a_feasible_path_and_remain_order_invariant() -> None:
    rows = [
        transaction("ab-too-late", "a", "b", 30, 9_000),
        transaction("ab-feasible", "a", "b", 0, 2_000),
        transaction("bc", "b", "c", 10, 1_900),
        transaction("ca", "c", "a", 20, 1_800),
    ]

    forward = detect_cycles(rows)
    reverse = detect_cycles(list(reversed(rows)))

    assert forward == reverse
    assert forward[0].transaction_ids == ("ab-feasible", "bc", "ca")
