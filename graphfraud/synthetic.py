from __future__ import annotations

from dataclasses import replace
import random

from .domain import Transaction


def synthetic_transactions(seed: int = 42, background_count: int = 160) -> list[Transaction]:
    rng = random.Random(seed)
    entities = [f"acct_{index:03d}" for index in range(40)]
    merchants = [f"merchant_{index:02d}" for index in range(8)]
    rows: list[Transaction] = []
    base = 1_760_000_000.0

    for index in range(background_count):
        src = rng.choice(entities)
        dst = rng.choice([entity for entity in entities + merchants if entity != src])
        amount = round(rng.lognormvariate(4.1, 0.8), 2)
        rows.append(
            Transaction(
                transaction_id=f"bg_{index:04d}",
                src=src,
                dst=dst,
                amount=amount,
                timestamp=base + rng.uniform(0, 86_400),
                channel=rng.choice(["card", "bank_transfer", "wallet"]),
                country_src=rng.choice(["US", "DE", "TR", "GB"]),
                country_dst=rng.choice(["US", "DE", "TR", "GB"]),
            )
        )

    # Rapid cycle: A -> B -> C -> A.
    rows.extend(
        [
            Transaction("cycle_1", "risk_cycle_a", "risk_cycle_b", 12_000, base + 20_000),
            Transaction("cycle_2", "risk_cycle_b", "risk_cycle_c", 11_700, base + 20_240),
            Transaction("cycle_3", "risk_cycle_c", "risk_cycle_a", 11_350, base + 20_480),
        ]
    )

    # Fan-in followed by concentrated outbound transfer.
    for index in range(7):
        rows.append(
            Transaction(
                f"fanin_{index}",
                f"sender_{index}",
                "risk_mule",
                1_200 + index * 110,
                base + 30_000 + index * 45,
            )
        )
    rows.append(Transaction("fanin_exit", "risk_mule", "offramp", 9_800, base + 30_600))

    # Layering chain with similar amounts and short gaps.
    chain = ["layer_a", "layer_b", "layer_c", "layer_d", "layer_e"]
    amount = 18_000.0
    for index in range(len(chain) - 1):
        rows.append(
            Transaction(
                f"layer_{index}",
                chain[index],
                chain[index + 1],
                amount,
                base + 40_000 + index * 180,
                country_src="TR" if index < 2 else "DE",
                country_dst="DE" if index >= 1 else "TR",
            )
        )
        amount *= 0.96

    rows.sort(key=lambda tx: tx.timestamp)
    return rows


def with_amount_multiplier(transactions: list[Transaction], multiplier: float) -> list[Transaction]:
    return [replace(tx, amount=round(tx.amount * multiplier, 2)) for tx in transactions]
