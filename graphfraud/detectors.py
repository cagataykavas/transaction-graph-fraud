from __future__ import annotations

from collections import defaultdict
import hashlib

import networkx as nx

from .domain import GraphFinding, Transaction
from .features import build_graph


def _severity(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.65:
        return "high"
    if score >= 0.40:
        return "medium"
    return "low"


def _finding_id(kind: str, entities: tuple[str, ...], tx_ids: tuple[str, ...]) -> str:
    raw = f"{kind}|{'|'.join(entities)}|{'|'.join(tx_ids)}"
    return f"{kind}-{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def detect_cycles(
    transactions: list[Transaction],
    *,
    max_cycle_length: int = 4,
    max_time_span_seconds: float = 3600.0,
    min_amount: float = 1000.0,
) -> list[GraphFinding]:
    graph = build_graph(transactions)
    simple = nx.DiGraph(graph)
    by_pair: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for tx in transactions:
        by_pair[(tx.src, tx.dst)].append(tx)

    findings: list[GraphFinding] = []
    seen: set[tuple[str, ...]] = set()
    for cycle in nx.simple_cycles(simple, length_bound=max_cycle_length):
        if len(cycle) < 3:
            continue
        canonical_rotations = [tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))]
        key = min(canonical_rotations)
        if key in seen:
            continue
        seen.add(key)

        selected: list[Transaction] = []
        valid = True
        for i, src in enumerate(cycle):
            dst = cycle[(i + 1) % len(cycle)]
            candidates = sorted(by_pair[(src, dst)], key=lambda tx: tx.timestamp)
            if not candidates:
                valid = False
                break
            selected.append(max(candidates, key=lambda tx: tx.amount))
        if not valid:
            continue

        timestamps = [tx.timestamp for tx in selected]
        amount_floor = min(tx.amount for tx in selected)
        span = max(timestamps) - min(timestamps)
        if span > max_time_span_seconds or amount_floor < min_amount:
            continue
        amount_similarity = amount_floor / (max(tx.amount for tx in selected) + 1e-9)
        time_compactness = max(0.0, 1.0 - span / max_time_span_seconds)
        score = min(1.0, 0.45 + 0.35 * amount_similarity + 0.20 * time_compactness)
        tx_ids = tuple(tx.transaction_id for tx in selected)
        entities = tuple(cycle)
        findings.append(
            GraphFinding(
                finding_id=_finding_id("cycle", entities, tx_ids),
                finding_type="rapid_fund_cycle",
                entities=entities,
                transaction_ids=tx_ids,
                score=score,
                severity=_severity(score),
                explanation=(
                    f"Funds traverse a {len(cycle)}-entity directed cycle within {span:.0f}s "
                    f"with minimum transferred amount {amount_floor:.2f}."
                ),
                evidence={"cycle_length": len(cycle), "time_span_seconds": span, "minimum_amount": amount_floor},
            )
        )
    return findings


def detect_fan_patterns(
    transactions: list[Transaction],
    *,
    window_seconds: float = 900.0,
    min_peers: int = 5,
    min_total_amount: float = 5000.0,
) -> list[GraphFinding]:
    findings: list[GraphFinding] = []
    for direction in ("fan_in", "fan_out"):
        grouped: dict[str, list[Transaction]] = defaultdict(list)
        for tx in transactions:
            grouped[tx.dst if direction == "fan_in" else tx.src].append(tx)

        for entity, rows in grouped.items():
            rows = sorted(rows, key=lambda tx: tx.timestamp)
            left = 0
            for right in range(len(rows)):
                while rows[right].timestamp - rows[left].timestamp > window_seconds:
                    left += 1
                window = rows[left : right + 1]
                peers = {tx.src if direction == "fan_in" else tx.dst for tx in window}
                total = sum(tx.amount for tx in window)
                if len(peers) < min_peers or total < min_total_amount:
                    continue
                peer_factor = min(1.0, len(peers) / max(min_peers * 2, 1))
                amount_factor = min(1.0, total / max(min_total_amount * 4, 1.0))
                score = min(1.0, 0.35 + 0.4 * peer_factor + 0.25 * amount_factor)
                tx_ids = tuple(tx.transaction_id for tx in window)
                entities = (entity, *tuple(sorted(peers)))
                findings.append(
                    GraphFinding(
                        finding_id=_finding_id(direction, entities, tx_ids),
                        finding_type=direction,
                        entities=entities,
                        transaction_ids=tx_ids,
                        score=score,
                        severity=_severity(score),
                        explanation=(
                            f"{entity} shows {direction.replace('_', '-')} behavior with {len(peers)} counterparties "
                            f"and {total:.2f} total value inside {window_seconds:.0f}s."
                        ),
                        evidence={"peer_count": len(peers), "total_amount": total, "window_seconds": window_seconds},
                    )
                )
                break
    return findings


def detect_layering_chains(
    transactions: list[Transaction],
    *,
    max_gap_seconds: float = 1200.0,
    amount_tolerance: float = 0.18,
    min_hops: int = 3,
) -> list[GraphFinding]:
    outgoing: dict[str, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        outgoing[tx.src].append(tx)
    for rows in outgoing.values():
        rows.sort(key=lambda tx: tx.timestamp)

    findings: list[GraphFinding] = []
    seen_paths: set[tuple[str, ...]] = set()

    def walk(path: list[Transaction]) -> None:
        last = path[-1]
        if len(path) >= min_hops:
            entities = (path[0].src, *(tx.dst for tx in path))
            if entities not in seen_paths:
                seen_paths.add(entities)
                ratios = [path[i + 1].amount / (path[i].amount + 1e-9) for i in range(len(path) - 1)]
                retained = min(ratios) if ratios else 1.0
                compactness = max(0.0, 1.0 - (path[-1].timestamp - path[0].timestamp) / (max_gap_seconds * len(path)))
                score = min(1.0, 0.35 + 0.4 * retained + 0.25 * compactness)
                tx_ids = tuple(tx.transaction_id for tx in path)
                findings.append(
                    GraphFinding(
                        finding_id=_finding_id("layer", entities, tx_ids),
                        finding_type="rapid_layering_chain",
                        entities=entities,
                        transaction_ids=tx_ids,
                        score=score,
                        severity=_severity(score),
                        explanation=(
                            f"Value moves through {len(path)} rapid hops with at least {retained:.1%} amount retention."
                        ),
                        evidence={"hops": len(path), "minimum_retention_ratio": retained},
                    )
                )
        if len(path) >= 5:
            return
        for nxt in outgoing.get(last.dst, []):
            if nxt.dst in {path[0].src, *(tx.dst for tx in path)}:
                continue
            gap = nxt.timestamp - last.timestamp
            if not 0 <= gap <= max_gap_seconds:
                continue
            ratio = nxt.amount / (last.amount + 1e-9)
            if abs(1.0 - ratio) <= amount_tolerance:
                walk(path + [nxt])

    for tx in transactions:
        walk([tx])
    return findings
