# Threshold structuring detector

The detector identifies repeated transfers that are individually below a configured review
threshold but cross it in aggregate inside a bounded time window. It evaluates inbound and outbound
directions separately and emits exact transaction IDs, counterparties, amounts, timing, currency,
and policy thresholds for human review.

```python
from graphfraud import StructuringPolicy, detect_threshold_structuring

findings = detect_threshold_structuring(
    transactions,
    policy=StructuringPolicy(
        review_threshold=10_000,
        currency="USD",
        window_seconds=3_600,
        min_transactions=4,
        min_distinct_peers=3,
    ),
)
```

## Production controls

- transfers at or above the review threshold are excluded from the split-transfer evidence;
- only one declared currency is analyzed per invocation, so monetary units are never mixed;
- duplicate transaction IDs, non-finite values, and excessive input sizes fail closed;
- stable event-time and transaction-ID ordering makes the output reproducible;
- one best bounded window is retained per entity and direction to limit alert duplication.

The default threshold is synthetic engineering configuration, not a statement of any jurisdiction's
reporting rule. A real deployment must use reviewed, versioned policy by jurisdiction, product,
currency, customer type, and effective date. The heuristic does not establish intent, criminality,
or transaction ownership, and foreign-currency flows require governed point-in-time conversion or
separate currency-specific policies.

The next increment should attach effective-dated policy lineage and evaluate alert precision on a
temporally held-out, investigator-reviewed cohort.
