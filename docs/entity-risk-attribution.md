# Exact entity-risk attribution

Every entity returned by the engine and API now includes a versioned `attribution` object that
reproduces its risk score from the same source of truth used for ranking.

The artifact exposes five reviewed components:

- counterparty breadth;
- transaction velocity;
- inbound/outbound flow imbalance;
- graph centrality and clustering;
- the highest-scoring detected typology.

For each component it records the source value, normalized value, model weight, and weighted
contribution. `pre_cap_score` is the additive total before the model's `[0, 1]` ceiling. When the
ceiling activates, `cap_adjustment` is explicit, so this invariant always holds:

```text
sum(component contributions) + cap_adjustment == predicted_score
```

The typology component also lists every tied finding ID that supplied its maximum. A deterministic
SHA-256 commitment covers the complete attribution artifact, making changed explanations visible
in regression evidence without claiming the digest is a signature.

The engine calls `explain_entity_risk` to calculate the production score rather than reconstructing
an explanation afterward. This avoids drift between scoring and explanation implementations.

## Limitations

This is exact decomposition of a transparent heuristic, not a causal explanation of criminal
behavior. Component weights and detector thresholds remain policy choices that require validation.
The attribution does not show interaction effects because the current score is additive, and the
cap adjustment can hide marginal changes once a score saturates at one.

The next increment should add reviewer-calibrated counterfactual sensitivity around alert
thresholds, with immutable feature and policy version identifiers bound into the artifact.
