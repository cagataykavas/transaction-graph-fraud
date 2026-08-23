from __future__ import annotations

from collections import defaultdict
from statistics import mean

import networkx as nx

from .domain import Transaction


def build_graph(transactions: list[Transaction]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for tx in transactions:
        graph.add_edge(
            tx.src,
            tx.dst,
            key=tx.transaction_id,
            transaction_id=tx.transaction_id,
            amount=tx.amount,
            timestamp=tx.timestamp,
            currency=tx.currency,
            channel=tx.channel,
            country_src=tx.country_src,
            country_dst=tx.country_dst,
        )
    return graph


def entity_features(transactions: list[Transaction]) -> dict[str, dict[str, float]]:
    graph = build_graph(transactions)
    incoming_amounts: dict[str, list[float]] = defaultdict(list)
    outgoing_amounts: dict[str, list[float]] = defaultdict(list)
    incoming_times: dict[str, list[float]] = defaultdict(list)
    outgoing_times: dict[str, list[float]] = defaultdict(list)

    for tx in transactions:
        outgoing_amounts[tx.src].append(tx.amount)
        incoming_amounts[tx.dst].append(tx.amount)
        outgoing_times[tx.src].append(tx.timestamp)
        incoming_times[tx.dst].append(tx.timestamp)

    simple = nx.DiGraph()
    for u, v, data in graph.edges(data=True):
        if simple.has_edge(u, v):
            simple[u][v]["amount"] += float(data["amount"])
            simple[u][v]["count"] += 1
        else:
            simple.add_edge(u, v, amount=float(data["amount"]), count=1)

    pagerank = nx.pagerank(simple, weight="amount") if simple.number_of_nodes() else {}
    clustering = nx.clustering(simple.to_undirected()) if simple.number_of_nodes() else {}

    result: dict[str, dict[str, float]] = {}
    for node in simple.nodes:
        ins = incoming_amounts[node]
        outs = outgoing_amounts[node]
        received = sum(ins)
        sent = sum(outs)
        total = received + sent
        peers = set(simple.predecessors(node)) | set(simple.successors(node))
        all_times = sorted(incoming_times[node] + outgoing_times[node])
        span = max(all_times) - min(all_times) if len(all_times) > 1 else 0.0
        velocity = (len(ins) + len(outs)) / max(span / 3600.0, 1.0)
        result[node] = {
            "in_degree": float(simple.in_degree(node)),
            "out_degree": float(simple.out_degree(node)),
            "unique_peers": float(len(peers)),
            "received_amount": received,
            "sent_amount": sent,
            "total_amount": total,
            "flow_ratio": sent / (received + 1e-9),
            "mean_incoming": mean(ins) if ins else 0.0,
            "mean_outgoing": mean(outs) if outs else 0.0,
            "transaction_velocity_per_hour": velocity,
            "pagerank": float(pagerank.get(node, 0.0)),
            "clustering": float(clustering.get(node, 0.0)),
        }
    return result
