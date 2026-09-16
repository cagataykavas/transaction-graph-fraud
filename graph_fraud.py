from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Transaction:
    src: str
    dst: str
    amount: float
    timestamp: float


def build_graph(transactions: list[Transaction]):
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for tx in transactions:
        outgoing[tx.src].append(tx)
        incoming[tx.dst].append(tx)
    return outgoing, incoming


def node_features(transactions: list[Transaction]) -> dict[str, dict[str, float]]:
    outgoing, incoming = build_graph(transactions)
    nodes = set(outgoing) | set(incoming)
    result = {}
    for node in nodes:
        outs, ins = outgoing[node], incoming[node]
        sent = sum(t.amount for t in outs)
        received = sum(t.amount for t in ins)
        peers = {t.dst for t in outs} | {t.src for t in ins}
        result[node] = {
            "out_degree": float(len(outs)),
            "in_degree": float(len(ins)),
            "unique_peers": float(len(peers)),
            "sent": sent,
            "received": received,
            "flow_ratio": sent / (received + 1e-9),
        }
    return result


def fraud_scores(transactions: list[Transaction]) -> dict[str, float]:
    features = node_features(transactions)
    scores = {}
    for node, f in features.items():
        churn = math.log1p(f["unique_peers"])
        imbalance = abs(math.log((f["sent"] + 1.0) / (f["received"] + 1.0)))
        activity = math.log1p(f["out_degree"] + f["in_degree"])
        scores[node] = 0.40 * churn + 0.35 * imbalance + 0.25 * activity
    return scores


def suspicious_cycles(transactions: list[Transaction], max_gap: float = 3600.0):
    edges = defaultdict(list)
    for tx in transactions:
        edges[(tx.src, tx.dst)].append(tx)
    findings = []
    nodes = {t.src for t in transactions} | {t.dst for t in transactions}
    for a in nodes:
        for ab in [t for t in transactions if t.src == a]:
            b = ab.dst
            for bc in [t for t in transactions if t.src == b and 0 <= t.timestamp - ab.timestamp <= max_gap]:
                c = bc.dst
                for ca in edges.get((c, a), []):
                    if 0 <= ca.timestamp - bc.timestamp <= max_gap:
                        findings.append((a, b, c, min(ab.amount, bc.amount, ca.amount)))
    return findings


if __name__ == "__main__":
    txs = [
        Transaction("alice", "bob", 9000, 0),
        Transaction("bob", "carol", 8800, 300),
        Transaction("carol", "alice", 8500, 600),
        Transaction("alice", "merchant", 50, 900),
        Transaction("dave", "merchant", 25, 1000),
    ]
    print("scores:", sorted(fraud_scores(txs).items(), key=lambda x: x[1], reverse=True))
    print("cycles:", suspicious_cycles(txs))
