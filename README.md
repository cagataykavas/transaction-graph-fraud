# Transaction Graph Fraud

![Architecture](docs/architecture.svg)

A runnable graph-analytics project for detecting suspicious transaction structures using **explicit, explainable network patterns** rather than a black-box score alone.

The public project uses deterministic synthetic data. It is designed to demonstrate graph engineering, financial-crime analytics, service boundaries and reviewer-facing evidence without containing real customer or employer data.

## What it detects

- **rapid fund cycles** such as `A → B → C → A`;
- **fan-in / fan-out** concentration patterns;
- **rapid layering chains** that preserve similar amounts across multiple hops;
- high transaction velocity and unusual inbound/outbound imbalance;
- graph features including degree, counterparty count, PageRank and clustering;
- ranked entity risk with human-readable reason codes.

The detectors intentionally expose their thresholds and evidence. This is a portfolio/reference system, not a claim that these heuristics are sufficient for a production AML program.

## Architecture

```mermaid
flowchart LR
    TX[JSONL / REST transactions] --> G[NetworkX graph]
    G --> F[Entity graph features]
    G --> C[Cycle detector]
    G --> P[Fan-in / fan-out detector]
    G --> L[Layering-chain detector]
    F --> R[Risk engine]
    C --> R
    P --> R
    L --> R
    R --> API[FastAPI]
    R --> JSON[JSON artifact]
    R --> HTML[Standalone HTML report]
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m graphfraud.cli --seed 42
```

This creates:

```text
artifacts/analysis.json
artifacts/report.html
```

Run the API:

```bash
uvicorn app.api:app --reload
```

Then:

```bash
curl http://localhost:8000/demo
```

or send your own synthetic/public transaction set to `POST /analyze`.

## Synthetic scenarios

`graphfraud/synthetic.py` generates ordinary background activity plus labeled-by-construction structures for engineering tests:

```text
risk_cycle_a -> risk_cycle_b -> risk_cycle_c -> risk_cycle_a

sender_0 --\
sender_1 ---\
...          > risk_mule -> offramp
sender_6 ---/

layer_a -> layer_b -> layer_c -> layer_d -> layer_e
```

These scenarios let CI verify that the graph pipeline still finds the expected *types* of structure after refactors.

## Package structure

```text
graphfraud/
  domain.py       transaction, finding and entity-risk models
  features.py     graph construction and entity-level features
  detectors.py    cycle, fan and layering typology detectors
  engine.py       finding aggregation and risk ranking
  synthetic.py    deterministic synthetic scenarios
  report.py       standalone HTML reviewer report
  cli.py          reproducible command-line run
  split_audit.py  train/test identity, topology and time contamination audit
app/
  api.py           FastAPI boundary
tests/
  test_graphfraud.py
```

## Engineering choices

**MultiDiGraph instead of a single weighted edge.** Multiple transfers between the same pair retain their own transaction IDs and timestamps, which matters when a finding must point back to evidence.

**Pattern findings stay separate from the entity score.** A reviewer can see *why* an entity was raised rather than receiving only one opaque probability.

**Deterministic synthetic cases.** They make tests reproducible and keep the public repository free of confidential datasets.

**Human review is the intended consumer.** Scores rank and summarize cases; they are not presented as autonomous enforcement decisions.

## Graph split contamination audit

An entity-level graph model can appear to generalize while the same accounts or directed
relationships occur in both training and test evidence. The audit makes that evaluation claim
explicit before model fitting:

```python
from graphfraud import GraphSplitPolicy, audit_graph_split

audit = audit_graph_split(train_transactions, test_transactions)
assert audit.accepted
```

The zero-overlap defaults represent **inductive entity generalization**. A temporal or
transductive backtest may deliberately permit known entities and relationships by setting the two
overlap limits, while still enforcing disjoint transaction IDs and a strict event-time/embargo
boundary. The result reports aggregate entity and directed-edge overlap rates, exact split sizes,
the observed temporal gap, reviewed policy, input commitments, finding codes, and a deterministic
evidence digest. It enforces the total transaction budget before inspecting members and rejects
malformed or non-finite transaction evidence.

This audit does not prove that labels, features, or upstream graph snapshots are point-in-time
correct. Identity commitments are integrity aids, not anonymization or producer authentication.
Production thresholds must match the declared evaluation objective; repeated accounts are
expected in some temporal monitoring designs and are not automatically leakage.

## Docker

```bash
docker build -t transaction-graph-fraud .
docker run --rm -p 8000:8000 transaction-graph-fraud
```

## Tests and CI

```bash
ruff check .
python -m pytest -q
```

GitHub Actions runs linting, tests, a complete CLI demo and a container build.

## Portfolio signal

This project is meant to make the following skills inspectable in one place:

**Python · NetworkX · graph analytics · financial crime patterns · explainability · FastAPI · Docker · CI/CD · synthetic data generation · human-review-oriented system design**
