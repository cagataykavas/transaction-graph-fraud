"""Currency-scoped detection of repeated sub-threshold transaction aggregation."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import isfinite

from .domain import GraphFinding, Transaction


@dataclass(frozen=True)
class StructuringPolicy:
    """Explicit engineering thresholds for the synthetic structuring detector."""

    review_threshold: float = 10_000.0
    currency: str = "USD"
    window_seconds: float = 3_600.0
    min_transactions: int = 4
    min_distinct_peers: int = 3
    min_amount_ratio: float = 0.20
    max_transactions: int = 100_000

    def __post_init__(self) -> None:
        for name, value in {
            "review_threshold": self.review_threshold,
            "window_seconds": self.window_seconds,
        }.items():
            if type(value) not in {int, float} or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")
        for name, value, maximum in (
            ("min_transactions", self.min_transactions, 10_000),
            ("min_distinct_peers", self.min_distinct_peers, 10_000),
            ("max_transactions", self.max_transactions, 1_000_000),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be an integer in [1, {maximum}]")
        if (
            type(self.min_amount_ratio) not in {int, float}
            or not isfinite(self.min_amount_ratio)
            or not 0 <= self.min_amount_ratio < 1
        ):
            raise ValueError("min_amount_ratio must be a finite number in [0, 1)")
        if (
            not isinstance(self.currency, str)
            or len(self.currency) != 3
            or not self.currency.isascii()
            or not self.currency.isupper()
            or not self.currency.isalpha()
        ):
            raise ValueError("currency must be a three-letter uppercase ASCII code")


def detect_threshold_structuring(
    transactions: list[Transaction],
    *,
    policy: StructuringPolicy | None = None,
) -> list[GraphFinding]:
    """Find bounded-window aggregates composed only of sub-threshold transfers.

    Currency is an explicit policy dimension. Transfers in other currencies are not
    converted or aggregated, preventing unit errors from becoming fraud evidence.
    """

    active = policy or StructuringPolicy()
    if len(transactions) > active.max_transactions:
        raise ValueError("transaction count exceeds the configured analysis budget")
    _validate_transactions(transactions, active.currency)

    floor = active.review_threshold * active.min_amount_ratio
    grouped: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for transaction in transactions:
        if (
            transaction.currency == active.currency
            and floor <= transaction.amount < active.review_threshold
        ):
            grouped[("fan_in", transaction.dst)].append(transaction)
            grouped[("fan_out", transaction.src)].append(transaction)

    findings: list[GraphFinding] = []
    for (direction, entity), rows in sorted(grouped.items()):
        finding = _best_window(direction, entity, rows, active)
        if finding is not None:
            findings.append(finding)
    return sorted(findings, key=lambda item: (-item.score, item.finding_id))


def _best_window(
    direction: str,
    entity: str,
    rows: list[Transaction],
    policy: StructuringPolicy,
) -> GraphFinding | None:
    ordered = sorted(rows, key=lambda tx: (tx.timestamp, tx.transaction_id))
    left = 0
    total = 0.0
    peer_counts: Counter[str] = Counter()
    best: tuple[tuple[float, ...], int, int, float, float] | None = None

    for right, transaction in enumerate(ordered):
        total += transaction.amount
        peer = transaction.src if direction == "fan_in" else transaction.dst
        peer_counts[peer] += 1
        while transaction.timestamp - ordered[left].timestamp > policy.window_seconds:
            expired = ordered[left]
            total -= expired.amount
            expired_peer = expired.src if direction == "fan_in" else expired.dst
            peer_counts[expired_peer] -= 1
            if peer_counts[expired_peer] == 0:
                del peer_counts[expired_peer]
            left += 1
        transaction_count = right - left + 1
        if (
            transaction_count < policy.min_transactions
            or len(peer_counts) < policy.min_distinct_peers
            or total < policy.review_threshold
        ):
            continue

        span = transaction.timestamp - ordered[left].timestamp
        amount_factor = min(1.0, total / (policy.review_threshold * 2.0))
        count_factor = min(1.0, transaction_count / (policy.min_transactions * 2.0))
        peer_factor = min(1.0, len(peer_counts) / (policy.min_distinct_peers * 2.0))
        compactness = max(0.0, 1.0 - span / policy.window_seconds)
        score = min(
            1.0,
            0.30
            + 0.30 * amount_factor
            + 0.15 * count_factor
            + 0.15 * peer_factor
            + 0.10 * compactness,
        )
        rank = (
            -score,
            -total,
            -float(transaction_count),
            span,
            ordered[left].timestamp,
            transaction.timestamp,
        )
        if best is None or rank < best[0]:
            best = (rank, left, right, total, score)

    if best is None:
        return None

    _, best_left, best_right, total, score = best
    window = ordered[best_left : best_right + 1]
    peers = {row.src if direction == "fan_in" else row.dst for row in window}
    span = window[-1].timestamp - window[0].timestamp
    transaction_ids = tuple(row.transaction_id for row in window)
    entities = (entity, *tuple(sorted(peers)))
    finding_id = _finding_id(
        direction,
        policy.currency,
        entities,
        transaction_ids,
    )
    return GraphFinding(
        finding_id=finding_id,
        finding_type="threshold_structuring",
        entities=entities,
        transaction_ids=transaction_ids,
        score=score,
        severity=_severity(score),
        explanation=(
            f"{entity} aggregates {len(window)} individually sub-threshold "
            f"{policy.currency} transfers totaling {total:.2f} within {span:.0f}s "
            f"in the {direction.replace('_', '-')} direction."
        ),
        evidence={
            "direction": direction,
            "currency": policy.currency,
            "transaction_count": len(window),
            "distinct_peer_count": len(peers),
            "aggregate_amount": total,
            "maximum_individual_amount": max(row.amount for row in window),
            "review_threshold": policy.review_threshold,
            "window_seconds": policy.window_seconds,
            "observed_span_seconds": span,
            "all_transfers_below_threshold": True,
        },
    )


def _validate_transactions(transactions: list[Transaction], currency: str) -> None:
    transaction_ids: set[str] = set()
    for transaction in transactions:
        if not transaction.transaction_id or len(transaction.transaction_id) > 256:
            raise ValueError("transaction IDs must be non-empty bounded strings")
        if transaction.transaction_id in transaction_ids:
            raise ValueError("transaction IDs must be unique")
        transaction_ids.add(transaction.transaction_id)
        if transaction.currency != currency:
            continue
        if not isfinite(transaction.amount) or transaction.amount < 0:
            raise ValueError("transaction amounts must be finite and non-negative")
        if not isfinite(transaction.timestamp):
            raise ValueError("transaction timestamps must be finite")


def _finding_id(
    direction: str,
    currency: str,
    entities: tuple[str, ...],
    transaction_ids: tuple[str, ...],
) -> str:
    payload = "|".join((direction, currency, *entities, *transaction_ids))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"structuring-{digest}"


def _severity(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.65:
        return "high"
    if score >= 0.40:
        return "medium"
    return "low"
