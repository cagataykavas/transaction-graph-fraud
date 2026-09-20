# Point-in-time graph validation

Graph fraud detectors must not evaluate a historical alert using edges that had
not arrived at the alert cutoff. `graphfraud.temporal_validation` builds
deterministic walk-forward folds that keep graph history, an optional embargo
period, and evaluation transactions separate.

```python
from graphfraud.temporal_validation import WalkForwardPolicy, build_walk_forward_folds

report = build_walk_forward_folds(
    transactions,
    WalkForwardPolicy(
        history_seconds=30 * 24 * 60 * 60,
        embargo_seconds=60 * 60,
        evaluation_seconds=24 * 60 * 60,
        step_seconds=24 * 60 * 60,
        min_history_transactions=1_000,
        min_evaluation_transactions=50,
    ),
)

for fold in report.folds:
    # Fit thresholds or construct the baseline graph only from fold.history.
    baseline = GraphFraudEngine().analyze(list(fold.history))
    # Score fold.evaluation after freezing any learned choices.
```

Intervals are left-closed and right-open. Transactions in the embargo interval
are retained as audit evidence but are not exposed to either side. Duplicate
transaction IDs, non-finite timestamps, invalid policies, insufficient sample
counts, and runs with no complete valid fold fail closed. Reports are JSON-ready
and include every transaction ID assigned to each interval.

## Interpretation and limits

The helper prevents direct future-edge leakage and makes sparse windows visible;
it does not itself label fraud, estimate detector precision, or model delayed
event arrival. Production evaluation still needs adjudicated outcomes, event-time
watermarks, late-data policy, and separate threshold selection. Overlapping
history or evaluation windows may create correlated fold metrics, so confidence
intervals must not treat folds as independent observations.
