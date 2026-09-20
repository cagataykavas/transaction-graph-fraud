from __future__ import annotations

import json
import math

import pytest

from graphfraud.domain import Transaction
from graphfraud.temporal_validation import WalkForwardPolicy, build_walk_forward_folds


def tx(transaction_id: str, timestamp: float) -> Transaction:
    return Transaction(transaction_id, f"src-{transaction_id}", "dst", 100.0, timestamp)


def test_builds_deterministic_point_in_time_folds_with_embargo():
    rows = [tx("e", 40), tx("a", 0), tx("d", 30), tx("b", 10), tx("c", 20), tx("f", 50)]
    policy = WalkForwardPolicy(
        history_seconds=20,
        embargo_seconds=10,
        evaluation_seconds=20,
        step_seconds=10,
        min_history_transactions=2,
    )

    report = build_walk_forward_folds(rows, policy)
    first = report.folds[0]

    assert [item.transaction_id for item in first.history] == ["a", "b"]
    assert [item.transaction_id for item in first.embargoed] == ["c"]
    assert [item.transaction_id for item in first.evaluation] == ["d", "e"]
    assert max(item.timestamp for item in first.history) < first.history_end
    assert min(item.timestamp for item in first.evaluation) >= first.evaluation_start
    assert json.loads(json.dumps(report.as_dict()))["fold_count"] == 1


def test_boundary_transaction_never_appears_in_history_and_evaluation():
    rows = [tx("a", 0), tx("b", 9), tx("cutoff", 10), tx("eval", 11), tx("end", 20)]
    report = build_walk_forward_folds(
        rows,
        WalkForwardPolicy(history_seconds=10, evaluation_seconds=10, step_seconds=10),
    )

    fold = report.folds[0]
    assert "cutoff" not in {item.transaction_id for item in fold.history}
    assert "cutoff" in {item.transaction_id for item in fold.evaluation}


def test_sparse_windows_are_counted_and_not_silently_used():
    rows = [tx("a", 0), tx("b", 30), tx("c", 40), tx("d", 50)]
    report = build_walk_forward_folds(
        rows,
        WalkForwardPolicy(
            history_seconds=10,
            evaluation_seconds=10,
            step_seconds=10,
            min_history_transactions=1,
        ),
    )

    assert report.skipped_windows == 3
    assert len(report.folds) == 1


@pytest.mark.parametrize(
    "rows, match",
    [
        ([tx("same", 0), tx("same", 10), tx("end", 20)], "duplicate"),
        ([tx("a", 0), tx("bad", math.inf), tx("end", 20)], "non-finite"),
        ([], "must not be empty"),
    ],
)
def test_rejects_ambiguous_or_invalid_transaction_evidence(rows, match):
    with pytest.raises(ValueError, match=match):
        build_walk_forward_folds(
            rows,
            WalkForwardPolicy(history_seconds=10, evaluation_seconds=10, step_seconds=10),
        )


def test_fails_closed_when_no_complete_fold_meets_minimums():
    with pytest.raises(ValueError, match="no complete fold"):
        build_walk_forward_folds(
            [tx("a", 0), tx("b", 10), tx("c", 20)],
            WalkForwardPolicy(
                history_seconds=10,
                evaluation_seconds=10,
                step_seconds=10,
                min_history_transactions=3,
            ),
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"history_seconds": 0, "evaluation_seconds": 1, "step_seconds": 1},
        {"history_seconds": 1, "evaluation_seconds": math.nan, "step_seconds": 1},
        {"history_seconds": 1, "evaluation_seconds": 1, "step_seconds": 1, "embargo_seconds": -1},
        {
            "history_seconds": 1,
            "evaluation_seconds": 1,
            "step_seconds": 1,
            "min_evaluation_transactions": 0,
        },
    ],
)
def test_rejects_invalid_policy(kwargs):
    with pytest.raises(ValueError):
        WalkForwardPolicy(**kwargs)
