# Investigation ranking audit

Graph detectors produce a risk-ranked entity queue, but investigators can review
only a bounded number of entities. Aggregate detector counts do not show whether
the highest-ranked portion of that queue captures adjudicated fraud cases.

`graphfraud.ranking_audit` evaluates the ranking at an explicit review capacity:

```python
from graphfraud.ranking_audit import (
    RankingAuditPolicy,
    RankingObservation,
    audit_investigation_ranking,
)

risks = GraphFraudEngine().entity_risks(transactions)
evidence = [
    RankingObservation(entity_id, risk.score, adjudicated_labels[entity_id])
    for entity_id, risk in risks.items()
]
report = audit_investigation_ranking(
    evidence,
    policy=RankingAuditPolicy(review_capacity=100),
)
```

## Tie-safe capacity metrics

A common implementation sorts equal scores by an entity ID and reports one
precision@K value. When an equal-score block crosses the analyst-capacity cutoff,
that result depends on an arbitrary secondary ordering.

The audit separates entities strictly above the cutoff from the boundary tie
block. It then reports conservative and optimistic bounds for:

- true positives captured;
- precision at review capacity;
- recall at review capacity; and
- lift over the labeled population base rate.

Admission thresholds are applied to the conservative lower bounds. A stricter
policy can reject every capacity-spanning tie with
`reject_ambiguous_cutoff=True`. The JSON-ready report retains the guaranteed and
boundary entity IDs, boundary slots, cutoff score, evidence counts, metrics, and
stable reason codes.

## Evidence contract

The evaluator fails closed on empty evidence, duplicate or blank entity IDs,
non-finite scores, non-binary labels, invalid policies, and review capacity larger
than the labeled population. Minimum labeled-entity and positive-case requirements
prevent a tiny apparently perfect sample from passing silently.

Labels should represent outcomes available at the evaluation cutoff. If fraud
adjudication is delayed, the queue must first be joined to mature outcomes; an
unobserved outcome is not a negative label.

## Limitations

This is a retrospective ranking audit, not a causal estimate of prevented loss.
It does not correct for investigation-selection bias, label noise, delayed fraud
discovery, entity networks crossing evaluation windows, or different case costs.
Exact floating-point scores define ties; deployments that intentionally quantize
scores should supply those quantized values.

The next production step is a walk-forward evaluation that freezes detectors and
thresholds, waits for mature adjudications, and reports these capacity metrics by
typology and operational cohort with uncertainty intervals.
