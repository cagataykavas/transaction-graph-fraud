from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, is_dataclass
from numbers import Real
from typing import Any

from .domain import Transaction

GRAPH_SPLIT_AUDIT_VERSION = "graphfraud-split-contamination/v1"


class GraphSplitAuditError(ValueError):
    """Raised when split evidence cannot be audited safely."""


@dataclass(frozen=True)
class GraphSplitPolicy:
    """Reviewed limits for an explicit train/test graph boundary.

    The zero-overlap defaults describe inductive entity generalization. A temporal
    or transductive evaluation must deliberately relax the overlap limits while
    retaining the transaction-identity and time-boundary checks.
    """

    max_test_entity_overlap_rate: float = 0.0
    max_test_edge_overlap_rate: float = 0.0
    require_strict_temporal_order: bool = True
    minimum_temporal_gap_seconds: float = 0.0
    min_train_transactions: int = 1
    min_test_transactions: int = 1
    max_transactions: int = 100_000

    def validate(self) -> None:
        for name, value in (
            ("max_test_entity_overlap_rate", self.max_test_entity_overlap_rate),
            ("max_test_edge_overlap_rate", self.max_test_edge_overlap_rate),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, Real)
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
            ):
                raise GraphSplitAuditError(f"{name} must be finite and in [0, 1]")
        if not isinstance(self.require_strict_temporal_order, bool):
            raise GraphSplitAuditError("require_strict_temporal_order must be boolean")
        if (
            isinstance(self.minimum_temporal_gap_seconds, bool)
            or not isinstance(self.minimum_temporal_gap_seconds, Real)
            or not math.isfinite(float(self.minimum_temporal_gap_seconds))
            or float(self.minimum_temporal_gap_seconds) < 0
        ):
            raise GraphSplitAuditError(
                "minimum_temporal_gap_seconds must be finite and non-negative"
            )
        for name, value in (
            ("min_train_transactions", self.min_train_transactions),
            ("min_test_transactions", self.min_test_transactions),
            ("max_transactions", self.max_transactions),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise GraphSplitAuditError(f"{name} must be a positive integer")
        if self.max_transactions > 1_000_000:
            raise GraphSplitAuditError("max_transactions cannot exceed 1000000")
        if (
            self.min_train_transactions + self.min_test_transactions
            > self.max_transactions
        ):
            raise GraphSplitAuditError(
                "minimum split sizes exceed the total transaction budget"
            )


@dataclass(frozen=True)
class GraphSplitAudit:
    schema_version: str
    accepted: bool
    policy: GraphSplitPolicy
    train_transaction_count: int
    test_transaction_count: int
    train_entity_count: int
    test_entity_count: int
    overlapping_entity_count: int
    test_entity_overlap_rate: float
    train_edge_count: int
    test_edge_count: int
    overlapping_edge_count: int
    test_edge_overlap_rate: float
    latest_train_timestamp: float
    earliest_test_timestamp: float
    temporal_gap_seconds: float
    train_sha256: str
    test_sha256: str
    findings: tuple[str, ...]
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_graph_split(
    train_transactions: Sequence[Transaction],
    test_transactions: Sequence[Transaction],
    *,
    policy: GraphSplitPolicy = GraphSplitPolicy(),
) -> GraphSplitAudit:
    """Audit identity, topology, and time contamination across a graph split."""

    policy.validate()
    if isinstance(train_transactions, (str, bytes)) or not isinstance(
        train_transactions, Sequence
    ):
        raise GraphSplitAuditError("train_transactions must be a transaction sequence")
    if isinstance(test_transactions, (str, bytes)) or not isinstance(
        test_transactions, Sequence
    ):
        raise GraphSplitAuditError("test_transactions must be a transaction sequence")

    train_count = len(train_transactions)
    test_count = len(test_transactions)
    if train_count < policy.min_train_transactions:
        raise GraphSplitAuditError("train split is below the minimum transaction count")
    if test_count < policy.min_test_transactions:
        raise GraphSplitAuditError("test split is below the minimum transaction count")
    if train_count + test_count > policy.max_transactions:
        raise GraphSplitAuditError("combined split exceeds the transaction budget")

    train_records = tuple(_transaction_record(tx) for tx in train_transactions)
    test_records = tuple(_transaction_record(tx) for tx in test_transactions)
    train_ids = {record["transaction_id"] for record in train_records}
    test_ids = {record["transaction_id"] for record in test_records}
    if len(train_ids) != train_count or len(test_ids) != test_count:
        raise GraphSplitAuditError("transaction IDs must be unique within each split")
    if train_ids & test_ids:
        raise GraphSplitAuditError("transaction IDs must be disjoint across splits")

    train_entities = _entities(train_records)
    test_entities = _entities(test_records)
    overlapping_entities = train_entities & test_entities
    train_edges = _edges(train_records)
    test_edges = _edges(test_records)
    overlapping_edges = train_edges & test_edges
    entity_overlap_rate = len(overlapping_entities) / len(test_entities)
    edge_overlap_rate = len(overlapping_edges) / len(test_edges)
    latest_train = max(float(record["timestamp"]) for record in train_records)
    earliest_test = min(float(record["timestamp"]) for record in test_records)
    temporal_gap = earliest_test - latest_train

    findings: list[str] = []
    if entity_overlap_rate > policy.max_test_entity_overlap_rate:
        findings.append("TEST_ENTITY_OVERLAP_LIMIT_EXCEEDED")
    if edge_overlap_rate > policy.max_test_edge_overlap_rate:
        findings.append("TEST_EDGE_OVERLAP_LIMIT_EXCEEDED")
    if (
        policy.require_strict_temporal_order
        and temporal_gap <= policy.minimum_temporal_gap_seconds
    ):
        findings.append("TEMPORAL_GAP_REQUIREMENT_BREACHED")

    payload = {
        "schema_version": GRAPH_SPLIT_AUDIT_VERSION,
        "accepted": not findings,
        "policy": policy,
        "train_transaction_count": train_count,
        "test_transaction_count": test_count,
        "train_entity_count": len(train_entities),
        "test_entity_count": len(test_entities),
        "overlapping_entity_count": len(overlapping_entities),
        "test_entity_overlap_rate": entity_overlap_rate,
        "train_edge_count": len(train_edges),
        "test_edge_count": len(test_edges),
        "overlapping_edge_count": len(overlapping_edges),
        "test_edge_overlap_rate": edge_overlap_rate,
        "latest_train_timestamp": latest_train,
        "earliest_test_timestamp": earliest_test,
        "temporal_gap_seconds": temporal_gap,
        "train_sha256": _digest(_sorted_records(train_records)),
        "test_sha256": _digest(_sorted_records(test_records)),
        "findings": tuple(findings),
    }
    return GraphSplitAudit(**payload, evidence_sha256=_digest(payload))


def _transaction_record(transaction: Transaction) -> dict[str, str | float]:
    if not isinstance(transaction, Transaction):
        raise GraphSplitAuditError("split members must be Transaction instances")
    record: dict[str, str | float] = {
        "transaction_id": _identifier(transaction.transaction_id, "transaction_id"),
        "src": _identifier(transaction.src, "src"),
        "dst": _identifier(transaction.dst, "dst"),
        "amount": _finite_number(transaction.amount, "amount", non_negative=True),
        "timestamp": _finite_number(transaction.timestamp, "timestamp"),
        "currency": _identifier(transaction.currency, "currency"),
        "channel": _identifier(transaction.channel, "channel"),
        "country_src": _identifier(transaction.country_src, "country_src"),
        "country_dst": _identifier(transaction.country_dst, "country_dst"),
    }
    if record["src"] == record["dst"]:
        raise GraphSplitAuditError("self-transfers are not valid split evidence")
    return record


def _identifier(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or not value.isprintable()
        or len(value) > 128
    ):
        raise GraphSplitAuditError(
            f"{name} must be a printable identifier of at most 128 characters"
        )
    return value


def _finite_number(value: Any, name: str, *, non_negative: bool = False) -> float:
    if isinstance(value, bool):
        raise GraphSplitAuditError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GraphSplitAuditError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or (non_negative and number < 0):
        qualifier = "finite and non-negative" if non_negative else "finite"
        raise GraphSplitAuditError(f"{name} must be {qualifier}")
    return number


def _entities(records: tuple[dict[str, str | float], ...]) -> set[str]:
    return {
        entity
        for record in records
        for entity in (str(record["src"]), str(record["dst"]))
    }


def _edges(records: tuple[dict[str, str | float], ...]) -> set[tuple[str, str]]:
    return {(str(record["src"]), str(record["dst"])) for record in records}


def _sorted_records(
    records: tuple[dict[str, str | float], ...],
) -> tuple[dict[str, str | float], ...]:
    return tuple(
        sorted(
            records,
            key=lambda record: (
                float(record["timestamp"]),
                str(record["transaction_id"]),
            ),
        )
    )


def _json_ready(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _digest(value: Any) -> str:
    rendered = json.dumps(
        _json_ready(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(rendered.encode()).hexdigest()
