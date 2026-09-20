from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from graphfraud.domain import Transaction


@dataclass(frozen=True)
class WalkForwardPolicy:
    """Bounded point-in-time windows for graph-detector evaluation."""

    history_seconds: float
    evaluation_seconds: float
    step_seconds: float
    embargo_seconds: float = 0.0
    min_history_transactions: int = 1
    min_evaluation_transactions: int = 1

    def __post_init__(self) -> None:
        positive = (self.history_seconds, self.evaluation_seconds, self.step_seconds)
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise ValueError("history, evaluation and step durations must be finite and positive")
        if not math.isfinite(self.embargo_seconds) or self.embargo_seconds < 0:
            raise ValueError("embargo_seconds must be finite and non-negative")
        if self.min_history_transactions < 1 or self.min_evaluation_transactions < 1:
            raise ValueError("minimum transaction counts must be positive integers")


@dataclass(frozen=True)
class TemporalFold:
    fold_index: int
    history_start: float
    history_end: float
    evaluation_start: float
    evaluation_end: float
    history: tuple[Transaction, ...]
    embargoed: tuple[Transaction, ...]
    evaluation: tuple[Transaction, ...]

    def __post_init__(self) -> None:
        if self.history and max(tx.timestamp for tx in self.history) >= self.history_end:
            raise ValueError("history contains information unavailable at its cutoff")
        if self.evaluation and min(tx.timestamp for tx in self.evaluation) < self.evaluation_start:
            raise ValueError("evaluation contains an embargo-period transaction")

    def as_dict(self) -> dict[str, object]:
        return {
            "fold_index": self.fold_index,
            "bounds": {
                "history_start": self.history_start,
                "history_end": self.history_end,
                "evaluation_start": self.evaluation_start,
                "evaluation_end": self.evaluation_end,
            },
            "counts": {
                "history": len(self.history),
                "embargoed": len(self.embargoed),
                "evaluation": len(self.evaluation),
            },
            "history_transaction_ids": [tx.transaction_id for tx in self.history],
            "embargoed_transaction_ids": [tx.transaction_id for tx in self.embargoed],
            "evaluation_transaction_ids": [tx.transaction_id for tx in self.evaluation],
        }


@dataclass(frozen=True)
class WalkForwardReport:
    policy: WalkForwardPolicy
    folds: tuple[TemporalFold, ...]
    skipped_windows: int

    def as_dict(self) -> dict[str, object]:
        return {
            "policy": asdict(self.policy),
            "fold_count": len(self.folds),
            "skipped_windows": self.skipped_windows,
            "folds": [fold.as_dict() for fold in self.folds],
        }


def build_walk_forward_folds(
    transactions: list[Transaction], policy: WalkForwardPolicy
) -> WalkForwardReport:
    """Create complete, deterministic folds without exposing future graph edges.

    Windows are left-closed and right-open. Transactions in the embargo interval
    are reported but belong to neither history nor evaluation.
    """

    if not transactions:
        raise ValueError("transactions must not be empty")

    seen: set[str] = set()
    for tx in transactions:
        if not tx.transaction_id:
            raise ValueError("transaction_id must not be empty")
        if tx.transaction_id in seen:
            raise ValueError(f"duplicate transaction_id: {tx.transaction_id}")
        seen.add(tx.transaction_id)
        if not math.isfinite(tx.timestamp):
            raise ValueError(f"non-finite timestamp for transaction: {tx.transaction_id}")

    ordered = tuple(sorted(transactions, key=lambda tx: (tx.timestamp, tx.transaction_id)))
    first_timestamp = ordered[0].timestamp
    last_timestamp = ordered[-1].timestamp
    history_start = first_timestamp
    history_end = history_start + policy.history_seconds
    folds: list[TemporalFold] = []
    skipped = 0
    fold_index = 0

    while (
        history_end + policy.embargo_seconds + policy.evaluation_seconds <= last_timestamp + 1e-12
    ):
        evaluation_start = history_end + policy.embargo_seconds
        evaluation_end = evaluation_start + policy.evaluation_seconds
        history = tuple(tx for tx in ordered if history_start <= tx.timestamp < history_end)
        embargoed = tuple(tx for tx in ordered if history_end <= tx.timestamp < evaluation_start)
        evaluation = tuple(
            tx for tx in ordered if evaluation_start <= tx.timestamp < evaluation_end
        )

        if (
            len(history) >= policy.min_history_transactions
            and len(evaluation) >= policy.min_evaluation_transactions
        ):
            folds.append(
                TemporalFold(
                    fold_index=fold_index,
                    history_start=history_start,
                    history_end=history_end,
                    evaluation_start=evaluation_start,
                    evaluation_end=evaluation_end,
                    history=history,
                    embargoed=embargoed,
                    evaluation=evaluation,
                )
            )
            fold_index += 1
        else:
            skipped += 1

        history_start += policy.step_seconds
        history_end += policy.step_seconds

    if not folds:
        raise ValueError("no complete fold satisfies the policy and minimum transaction counts")
    return WalkForwardReport(policy=policy, folds=tuple(folds), skipped_windows=skipped)
